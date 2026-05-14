"""
Web UI for the Job Scraper.

Provides a visual browser-based interface so non-technical users
can search for jobs without touching the command line.

Run:
    uv run job-scraper ui
    uv run python main.py ui
"""

import json
import logging
import threading
import webbrowser
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, send_file, render_template, request

from job_scraper import config
from job_scraper.query_parser import parse_query
from job_scraper.scraper import run_scraper
from job_scraper.processing import process_jobs
from job_scraper.logger import setup_task_logger

# Suppress Flask/Werkzeug access logs (GET /status etc.)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

app = Flask(__name__)

# ── shared state for progress tracking ──
_logs_dict = {}
_state_dict = {}  # {task_id: {"status": "idle", "result_count": 0, "error": ""}}
_task_order = []  # track insertion order for cleanup
_cancel_flags = set()
_state_lock = threading.Lock()
_MAX_STORED_TASKS = 50


def _cleanup_old_tasks():
    """Remove oldest tasks when exceeding the storage limit."""
    with _state_lock:
        while len(_task_order) > _MAX_STORED_TASKS:
            old_id = _task_order.pop(0)
            _state_dict.pop(old_id, None)
            _logs_dict.pop(old_id, None)
            _cancel_flags.discard(old_id)


def _init_task(task_id):
    with _state_lock:
        _state_dict[task_id] = {
            "status": "running",
            "result_count": 0,
            "error": "",
        }
        _logs_dict[task_id] = []
        _task_order.append(task_id)
    _cleanup_old_tasks()


def _set_status(task_id, status, **kwargs):
    with _state_lock:
        if task_id not in _state_dict:
            _state_dict[task_id] = {}
        _state_dict[task_id]["status"] = status
        for k, v in kwargs.items():
            _state_dict[task_id][k] = v


# ── HTML page (embedded for zero-config) ──

@app.route("/")
def index():
    return render_template("index.html")


# ── Job role taxonomy for smart suggestions ──
_ROLE_TAXONOMY = {
    # ═══ TECH / ENGINEERING ═══
    "AI / Machine Learning": [
        "AI Engineer", "Machine Learning Engineer", "ML Ops Engineer",
        "NLP Engineer", "Computer Vision Engineer", "Deep Learning Engineer",
        "AI Research Scientist", "Prompt Engineer", "AI Product Manager",
        "Conversational AI Developer", "Robotics Engineer",
        "AI Trainer", "AI Ethics Specialist", "Generative AI Engineer",
        "Reinforcement Learning Engineer", "Speech Recognition Engineer",
    ],
    "Backend Development": [
        "Backend Developer", "Python Developer", "Java Developer",
        "Go Developer", "Node.js Developer", "PHP Developer",
        "Ruby Developer", "Rust Developer", "C# / .NET Developer",
        "Scala Developer", "Elixir Developer", "Perl Developer",
        "API Developer", "Microservices Engineer", "Backend Architect",
    ],
    "Frontend Development": [
        "Frontend Developer", "React Developer", "Angular Developer",
        "Vue.js Developer", "Svelte Developer", "TypeScript Developer",
        "UI Developer", "Web Developer", "JavaScript Developer",
        "Next.js Developer", "Nuxt.js Developer", "Frontend Architect",
        "Webflow Developer", "WordPress Developer",
    ],
    "Full Stack": [
        "Full Stack Developer", "Full Stack Engineer",
        "MERN Stack Developer", "MEAN Stack Developer",
        "Django Full Stack Developer", "Rails Full Stack Developer",
        "T-Shaped Developer",
    ],
    "Mobile Development": [
        "iOS Developer", "Android Developer", "React Native Developer",
        "Flutter Developer", "Mobile Engineer", "Swift Developer",
        "Kotlin Developer", "Xamarin Developer", "Mobile Architect",
        "Mobile QA Engineer", "Mobile DevOps Engineer",
    ],
    "Data & Analytics": [
        "Data Engineer", "Data Analyst", "Data Scientist",
        "Business Intelligence Analyst", "BI Developer", "Analytics Engineer",
        "ETL Developer", "Data Architect", "Database Administrator",
        "Data Warehouse Engineer", "Data Visualization Specialist",
        "Power BI Developer", "Tableau Developer", "Looker Developer",
        "Big Data Engineer", "Hadoop Engineer", "Spark Developer",
        "Data Governance Analyst", "Data Quality Engineer",
        "Quantitative Analyst", "Statistical Analyst",
    ],
    "DevOps / Cloud / Infrastructure": [
        "DevOps Engineer", "Site Reliability Engineer", "Cloud Engineer",
        "Platform Engineer", "Infrastructure Engineer",
        "AWS Solutions Architect", "AWS Engineer", "Azure Engineer",
        "GCP Engineer", "Cloud Architect", "Cloud Security Engineer",
        "Kubernetes Engineer", "Docker Specialist",
        "Systems Administrator", "Linux Administrator",
        "Network Engineer", "Network Administrator",
        "Release Engineer", "Build Engineer", "CI/CD Engineer",
        "Terraform Engineer", "Ansible Engineer",
    ],
    "Cybersecurity": [
        "Security Engineer", "Cybersecurity Analyst", "Penetration Tester",
        "Security Architect", "SOC Analyst", "AppSec Engineer",
        "Information Security Manager", "Security Operations Engineer",
        "Threat Intelligence Analyst", "Incident Response Analyst",
        "Cloud Security Specialist", "Compliance Analyst",
        "Ethical Hacker", "Red Team Operator", "Blue Team Analyst",
        "GRC Analyst", "CISO", "Identity & Access Management Engineer",
    ],
    "QA / Testing": [
        "QA Engineer", "Test Automation Engineer", "SDET",
        "Quality Assurance Analyst", "Performance Tester",
        "QA Lead", "Manual Tester", "Regression Tester",
        "Test Manager", "Accessibility Tester",
        "Selenium Engineer", "Cypress Developer",
        "Load Testing Engineer", "Security Tester",
    ],
    "Embedded / IoT / Hardware": [
        "Embedded Systems Engineer", "Firmware Engineer",
        "IoT Developer", "FPGA Engineer", "Hardware Engineer",
        "RTOS Developer", "Embedded C Developer",
        "PCB Designer", "Electronics Engineer", "Signal Processing Engineer",
        "Automotive Software Engineer", "Robotics Software Engineer",
    ],
    "Blockchain / Web3": [
        "Blockchain Developer", "Solidity Developer",
        "Smart Contract Developer", "Web3 Developer",
        "DeFi Developer", "Crypto Engineer",
        "NFT Developer", "dApp Developer",
        "Blockchain Architect", "Token Economist",
    ],
    "ERP / Enterprise": [
        "SAP Developer", "SAP Consultant", "SAP ABAP Developer",
        "Salesforce Developer", "Salesforce Administrator",
        "ServiceNow Developer", "Oracle Developer",
        "ERP Consultant", "ERP Implementation Specialist",
        "Dynamics 365 Developer", "HubSpot Developer",
    ],

    # ═══ DESIGN & CREATIVE ═══
    "UX / UI Design": [
        "UX Designer", "UI Designer", "UX/UI Designer",
        "Product Designer", "Interaction Designer", "UX Researcher",
        "Visual Designer", "Design Systems Engineer",
        "Service Designer", "Information Architect",
        "UX Writer", "Design Lead", "Design Director",
        "Figma Designer", "Prototyping Specialist",
    ],
    "2D Art & Illustration": [
        "2D Artist", "Illustrator", "Digital Illustrator",
        "Character Designer", "Background Artist",
        "Storyboard Artist", "Comic Artist",
        "Pixel Artist", "Icon Designer", "Pattern Designer",
        "Key Visual Artist", "Matte Painter",
        "Children's Book Illustrator", "Editorial Illustrator",
        "Vector Artist", "Sprite Artist",
    ],
    "3D Art & Modeling": [
        "3D Artist", "3D Modeler", "3D Animator", "3D Generalist",
        "3D Environment Artist", "3D Character Artist",
        "Hard Surface Modeler", "Texture Artist",
        "Lighting Artist", "Rendering Artist",
        "3D Visualization Artist", "Architectural Visualizer",
        "Product Visualizer", "3D Scanning Specialist",
    ],
    "Game Development": [
        "Game Developer", "Unity Developer", "Unreal Developer",
        "Game Designer", "Level Designer", "Systems Designer",
        "Gameplay Programmer", "Game AI Programmer",
        "Technical Artist", "Shader Developer",
        "Game Producer", "Narrative Designer",
        "Game QA Tester", "Game Economy Designer",
        "Multiplayer Engineer", "Game Tools Developer",
        "Godot Developer",
    ],
    "Motion & Video": [
        "Motion Designer", "Motion Graphics Artist",
        "Video Editor", "Colorist", "Compositor",
        "VFX Artist", "VFX Supervisor", "VFX Compositor",
        "After Effects Artist", "Cinema 4D Artist",
        "Houdini Artist", "Nuke Artist",
        "Video Producer", "Broadcast Designer",
        "Title Designer", "Visual Effects Producer",
    ],
    "Graphic Design": [
        "Graphic Designer", "Brand Designer", "Logo Designer",
        "Print Designer", "Packaging Designer",
        "Publication Designer", "Layout Designer",
        "Presentation Designer", "Infographic Designer",
        "Environmental Graphic Designer", "Signage Designer",
        "Creative Director", "Art Director", "Design Manager",
    ],

    # ═══ MARKETING & GROWTH ═══
    "Digital Marketing": [
        "Digital Marketing Manager", "Digital Marketing Specialist",
        "Performance Marketing Manager", "Growth Marketing Manager",
        "Marketing Automation Specialist", "Conversion Rate Optimizer",
        "Campaign Manager", "Demand Generation Manager",
        "Marketing Analyst", "Marketing Data Analyst",
        "Acquisition Manager", "Retention Marketing Manager",
        "Lifecycle Marketing Manager", "CRM Manager",
        "Email Marketing Manager", "Email Marketing Specialist",
        "Push Notification Manager", "Marketing Operations Manager",
    ],
    "SMM / Social Media": [
        "SMM Manager", "Social Media Manager", "Social Media Specialist",
        "Social Media Strategist", "Community Manager",
        "Social Media Analyst", "Social Media Content Creator",
        "Influencer Marketing Manager", "Influencer Relations Manager",
        "TikTok Manager", "Instagram Manager", "YouTube Manager",
        "Social Media Moderator", "Online Reputation Manager",
        "Social Listening Analyst", "Social Media Coordinator",
    ],
    "Content & Copywriting": [
        "Content Manager", "Content Strategist", "Content Director",
        "Copywriter", "Senior Copywriter", "Creative Copywriter",
        "UX Writer", "Technical Writer", "Content Writer",
        "Blog Writer", "Ghostwriter", "Scriptwriter",
        "SEO Copywriter", "Content Marketing Manager",
        "Content Editor", "Managing Editor", "Editor-in-Chief",
        "Brand Journalist", "Content Producer",
        "Localization Manager", "Translation Manager",
    ],
    "SEO / SEM / PPC": [
        "SEO Specialist", "SEO Manager", "SEO Analyst",
        "SEM Specialist", "SEM Manager",
        "PPC Specialist", "PPC Manager", "Google Ads Specialist",
        "Paid Media Specialist", "Paid Social Specialist",
        "Facebook Ads Manager", "Amazon Ads Specialist",
        "Programmatic Specialist", "Media Buyer",
        "Search Marketing Manager", "ASO Specialist",
    ],
    "PR & Communications": [
        "PR Manager", "PR Specialist", "Press Officer",
        "Communications Manager", "Communications Director",
        "Corporate Communications Manager", "Internal Communications Manager",
        "Public Affairs Manager", "Government Relations Manager",
        "Media Relations Manager", "Spokesperson",
        "Crisis Communications Manager", "Reputation Manager",
    ],
    "Brand & Creative Strategy": [
        "Brand Manager", "Brand Strategist", "Brand Director",
        "Creative Director", "Creative Strategist",
        "Chief Marketing Officer", "VP of Marketing",
        "Head of Brand", "Marketing Director",
    ],

    # ═══ SALES & BUSINESS DEVELOPMENT ═══
    "B2B Sales": [
        "B2B Sales Manager", "B2B Sales Representative",
        "Enterprise Sales Manager", "Enterprise Account Executive",
        "Account Executive", "Account Manager",
        "Sales Development Representative", "SDR",
        "Business Development Representative", "BDR",
        "Inside Sales Representative", "Outside Sales Representative",
        "Regional Sales Manager", "Territory Sales Manager",
        "Channel Sales Manager", "Partner Sales Manager",
        "Solutions Engineer", "Sales Engineer", "Pre-Sales Engineer",
        "Key Account Manager", "Strategic Account Manager",
        "VP of Sales", "Chief Revenue Officer", "Head of Sales",
    ],
    "B2C Sales & Retail": [
        "B2C Sales Manager", "Retail Manager", "Store Manager",
        "E-commerce Manager", "E-commerce Specialist",
        "Online Sales Manager", "Marketplace Manager",
        "Amazon Seller Manager", "Shopify Specialist",
        "Sales Associate", "Sales Consultant",
    ],
    "Business Development": [
        "Business Development Manager", "Business Development Director",
        "Business Development Representative",
        "Partnerships Manager", "Strategic Partnerships Manager",
        "Alliance Manager", "Vendor Manager",
        "Market Development Manager", "Growth Manager",
        "Expansion Manager", "New Markets Manager",
    ],
    "Customer Success & Support": [
        "Customer Success Manager", "Customer Success Director",
        "Customer Experience Manager", "Client Relations Manager",
        "Customer Support Specialist", "Customer Support Manager",
        "Technical Support Engineer", "Help Desk Analyst",
        "Implementation Specialist", "Onboarding Specialist",
        "Client Solutions Manager", "Customer Advocate",
        "Customer Operations Manager",
    ],

    # ═══ PRODUCT & PROJECT MANAGEMENT ═══
    "Product Management": [
        "Product Manager", "Senior Product Manager",
        "Technical Product Manager", "AI Product Manager",
        "Growth Product Manager", "Platform Product Manager",
        "Product Owner", "Product Lead", "Product Director",
        "VP of Product", "Chief Product Officer",
        "Product Analyst", "Product Operations Manager",
    ],
    "Project & Program Management": [
        "Project Manager", "Technical Project Manager",
        "IT Project Manager", "Construction Project Manager",
        "Program Manager", "Portfolio Manager",
        "Scrum Master", "Agile Coach", "Agile Project Manager",
        "Delivery Manager", "Release Manager",
        "PMO Manager", "PMO Director",
    ],
    "Engineering Management": [
        "Engineering Manager", "VP of Engineering",
        "Director of Engineering", "CTO",
        "Tech Lead", "Team Lead", "Staff Engineer",
        "Principal Engineer", "Distinguished Engineer",
        "Head of Engineering",
    ],

    # ═══ HR & PEOPLE ═══
    "HR / People Operations": [
        "HR Manager", "HR Specialist", "HR Generalist",
        "HR Business Partner", "HR Director", "VP of People",
        "Chief People Officer", "Head of HR",
        "People Operations Manager", "HR Operations Specialist",
        "HR Analyst", "HR Data Analyst",
        "Employee Experience Manager", "Culture Manager",
        "Diversity & Inclusion Manager", "DEI Specialist",
        "Organizational Development Specialist",
        "Change Management Specialist",
    ],
    "Recruitment / Talent Acquisition": [
        "Recruiter", "Technical Recruiter", "IT Recruiter",
        "Senior Recruiter", "Lead Recruiter",
        "Talent Acquisition Manager", "Talent Acquisition Partner",
        "Sourcing Specialist", "Headhunter",
        "Recruitment Marketing Specialist", "Employer Branding Manager",
        "Recruitment Operations Manager",
        "Campus Recruiter", "Executive Recruiter",
    ],
    "Learning & Development": [
        "L&D Manager", "Training Manager", "Training Specialist",
        "Instructional Designer", "E-Learning Developer",
        "Learning Experience Designer", "Knowledge Manager",
        "Corporate Trainer", "Coaching Manager",
        "Talent Development Manager",
    ],
    "Compensation & Benefits": [
        "Compensation Analyst", "Benefits Manager",
        "Total Rewards Manager", "Payroll Manager",
        "Payroll Specialist", "HRIS Analyst",
        "Workday Administrator",
    ],

    # ═══ FINANCE & ACCOUNTING ═══
    "Finance": [
        "Financial Analyst", "Senior Financial Analyst",
        "FP&A Analyst", "FP&A Manager",
        "Finance Manager", "Finance Director", "CFO",
        "Investment Analyst", "Portfolio Manager",
        "Risk Analyst", "Risk Manager",
        "Treasury Analyst", "Treasury Manager",
        "Revenue Analyst", "Pricing Analyst",
        "Financial Controller", "Finance Business Partner",
        "FinTech Developer", "Quantitative Developer",
    ],
    "Accounting": [
        "Accountant", "Senior Accountant", "Staff Accountant",
        "Tax Accountant", "Tax Manager",
        "Audit Manager", "Internal Auditor", "External Auditor",
        "Accounts Payable Specialist", "Accounts Receivable Specialist",
        "Bookkeeper", "Billing Specialist",
        "Accounting Manager", "Controller",
    ],

    # ═══ OPERATIONS & LOGISTICS ═══
    "Operations": [
        "Operations Manager", "Operations Director", "COO",
        "Business Operations Manager", "Revenue Operations Manager",
        "Sales Operations Manager", "Marketing Operations Manager",
        "Operations Analyst", "Process Improvement Manager",
        "Lean Specialist", "Six Sigma Specialist",
    ],
    "Supply Chain & Logistics": [
        "Supply Chain Manager", "Supply Chain Analyst",
        "Logistics Manager", "Logistics Coordinator",
        "Procurement Manager", "Procurement Specialist",
        "Sourcing Manager", "Category Manager",
        "Inventory Manager", "Demand Planner",
        "Warehouse Manager", "Distribution Manager",
        "Import/Export Specialist", "Customs Specialist",
        "Fleet Manager", "Transportation Manager",
    ],

    # ═══ LEGAL & COMPLIANCE ═══
    "Legal & Compliance": [
        "Legal Counsel", "Corporate Lawyer", "In-House Counsel",
        "Legal Manager", "General Counsel",
        "Compliance Manager", "Compliance Officer",
        "Regulatory Affairs Manager", "Regulatory Specialist",
        "Contract Manager", "Contract Specialist",
        "Privacy Officer", "DPO (Data Protection Officer)",
        "IP Lawyer", "Patent Attorney",
        "Paralegal", "Legal Assistant",
        "KYC Analyst", "AML Analyst",
    ],

    # ═══ CONSULTING & STRATEGY ═══
    "Consulting & Strategy": [
        "Management Consultant", "Strategy Consultant",
        "Business Consultant", "IT Consultant",
        "Digital Transformation Consultant",
        "Technology Consultant", "SAP Consultant",
        "Business Analyst", "Systems Analyst",
        "Solutions Architect", "Enterprise Architect",
        "Change Management Consultant",
        "Process Consultant", "Lean Consultant",
    ],

    # ═══ EDUCATION & TRAINING ═══
    "Education & EdTech": [
        "Online Instructor", "Course Creator",
        "Curriculum Developer", "EdTech Product Manager",
        "LMS Administrator", "Academic Coordinator",
        "Tutor", "Mentor", "Education Consultant",
        "STEM Educator", "Coding Bootcamp Instructor",
    ],

    # ═══ HEALTHCARE IT ═══
    "HealthTech / MedTech": [
        "Health Informatics Specialist", "Clinical Data Manager",
        "Bioinformatics Engineer", "Healthcare Data Analyst",
        "Medical Device Engineer", "Regulatory Affairs Specialist",
        "Telehealth Developer", "EHR Specialist",
        "Clinical Systems Analyst", "Pharma Data Scientist",
    ],

    # ═══ MEDIA & JOURNALISM ═══
    "Media & Journalism": [
        "Journalist", "Reporter", "Editor",
        "Multimedia Journalist", "Investigative Journalist",
        "Podcast Producer", "Audio Engineer",
        "Photographer", "Photojournalist",
        "News Producer", "Assignment Editor",
    ],

    # ═══ ARCHITECTURE & CONSTRUCTION ═══
    "Architecture & Construction": [
        "Architect", "Interior Designer", "Landscape Architect",
        "BIM Manager", "BIM Modeler",
        "Urban Planner", "Spatial Designer",
        "Structural Engineer", "Construction Manager",
        "Quantity Surveyor", "Estimator",
    ],

    # ═══ REAL ESTATE ═══
    "Real Estate & PropTech": [
        "Real Estate Agent", "Property Manager",
        "Real Estate Analyst", "Investment Analyst",
        "PropTech Developer", "Leasing Manager",
        "Asset Manager", "Facilities Manager",
    ],

    # ═══ NON-PROFIT & NGO ═══
    "Non-Profit & NGO": [
        "Program Manager", "Grant Writer", "Fundraiser",
        "Volunteer Coordinator", "Community Organizer",
        "Advocacy Manager", "Policy Analyst",
        "Humanitarian Worker", "NGO Project Manager",
    ],

    # ═══ RESEARCH & SCIENCE ═══
    "Research & Science": [
        "Research Scientist", "Research Engineer",
        "R&D Engineer", "Lab Technician",
        "Research Analyst", "Research Associate",
        "Computational Scientist", "Materials Scientist",
        "Biotech Researcher", "Clinical Research Associate",
    ],
}


@app.route("/suggest")
def suggest():
    """Return matching job role suggestions based on user input."""
    q = request.args.get("q", "").strip().lower()
    if len(q) < 2:
        return jsonify([])

    # Transliterate Cyrillic input for matching
    from job_scraper.query_parser import _transliterate_tech_terms
    q_en = _transliterate_tech_terms(q).lower()

    results = []
    seen = set()

    for domain, roles in _ROLE_TAXONOMY.items():
        for role in roles:
            role_lower = role.lower()
            # Match against both original and transliterated query
            if q_en in role_lower or q in role_lower:
                if role_lower not in seen:
                    seen.add(role_lower)
                    results.append({"role": role, "domain": domain})

    # Also match domain names
    for domain, roles in _ROLE_TAXONOMY.items():
        if q_en in domain.lower() or q in domain.lower():
            for role in roles:
                if role.lower() not in seen:
                    seen.add(role.lower())
                    results.append({"role": role, "domain": domain})

    return jsonify(results[:20])

@app.route("/search", methods=["POST"])
def search():
    data = request.get_json(force=True)
    query_text = str(data.get("query", "")).strip()

    # Input validation
    if not query_text:
        return jsonify({"ok": False, "error": "Query cannot be empty"}), 400
    if len(query_text) > 2000:
        return jsonify({"ok": False, "error": "Query too long (max 2000 chars)"}), 400

    try:
        workers = int(data.get("workers", 3))
    except (TypeError, ValueError):
        workers = 3
    workers = max(1, min(10, workers))

    # Extract selected sites from frontend
    selected_sites = data.get("sites", ["linkedin", "indeed"])
    if not isinstance(selected_sites, list) or not selected_sites:
        selected_sites = ["linkedin", "indeed"]

    parsed = parse_query(query_text)
    parsed.workers = workers
    parsed.sites = selected_sites

    task_id = str(uuid.uuid4())
    _init_task(task_id)

    # Return parsed info immediately, scraping runs in background
    thread = threading.Thread(
        target=_run_scraper_background,
        args=(parsed, task_id),
        daemon=True,
    )
    thread.start()

    return jsonify({
        "ok": True,
        "task_id": task_id,
        "parsed": {
            "job_title": parsed.job_title,
            "count": parsed.count,
            "remote": parsed.remote,
            "locations": parsed.locations,
            "max_age_hours": parsed.max_age_hours,
            "salary_filter": parsed.salary_filter,
        },
    })


@app.route("/cancel", methods=["POST"])
def cancel():
    data = request.get_json(force=True)
    task_id = data.get("task_id")
    if task_id:
        _cancel_flags.add(task_id)
        _set_status(task_id, "error", error="Cancelled by user")
    return jsonify({"ok": True})

@app.route("/status")
def status():
    task_id = request.args.get("task_id")
    with _state_lock:
        if not task_id or task_id not in _state_dict:
            return jsonify({"status": "error", "error": "Invalid task ID"})
        
        resp = dict(_state_dict[task_id])
        resp["progress"] = list(_logs_dict.get(task_id, []))
        return jsonify(resp)


@app.route("/results")
def results():
    import pandas as pd

    csv_path = config.FINAL_CSV
    if not csv_path.exists():
        return jsonify([])

    try:
        df = pd.read_csv(csv_path)
    except pd.errors.EmptyDataError:
        return jsonify([])

    cols = ["company", "position", "location", "url", "description"]
    for c in cols:
        if c not in df.columns:
            df[c] = ""

    records = df[cols].fillna("").head(500).to_dict(orient="records")
    return jsonify(records)


@app.route("/analytics")
def analytics():
    import pandas as pd
    import re
    from collections import Counter
    
    csv_path = config.FINAL_CSV
    if not csv_path.exists():
        return jsonify({})
        
    try:
        df = pd.read_csv(csv_path)
    except pd.errors.EmptyDataError:
        return jsonify({"total_jobs": 0})

    if df.empty:
        return jsonify({"total_jobs": 0})
        
    loc_counts = df['location'].value_counts().head(7).to_dict()
    comp_counts = df['company'].value_counts().head(7).to_dict()
    
    sources_raw = df.get('source', pd.Series(dtype=str)).value_counts().to_dict()
    sources = {}
    for k, v in sources_raw.items():
        k_str = str(k)
        # Proper capitalization for known sites
        if k_str.lower() == 'linkedin': sources['LinkedIn'] = v
        elif k_str.lower() == 'indeed': sources['Indeed'] = v
        elif k_str.lower() == 'glassdoor': sources['Glassdoor'] = v
        elif k_str.lower() == 'zip_recruiter': sources['ZipRecruiter'] = v
        else: sources[k_str.capitalize()] = v
    if not sources: sources = {"LinkedIn": len(df)}
    
    salaries = []
    if 'min_amount' in df.columns and 'max_amount' in df.columns:
        for _, row in df.iterrows():
            try:
                mn = float(row.get('min_amount'))
                mx = float(row.get('max_amount'))
                if pd.notna(mn) and pd.notna(mx) and mn > 0:
                    salaries.append((mn + mx) / 2)
            except (TypeError, ValueError):
                pass
                
    if len(salaries) < 5:
        for desc in df['description'].dropna():
            matches = re.findall(r'[\$€£]\s*(\d{2,3})[kK]', str(desc))
            for match in matches:
                try:
                    val = float(match) * 1000
                    if 20000 <= val <= 300000:
                        salaries.append(val)
                except (TypeError, ValueError):
                    pass
            matches = re.findall(r'[\$€£]\s*(\d{2,3}),(\d{3})', str(desc))
            for amount_k, amount_rest in matches:
                try:
                    val = float(amount_k + amount_rest)
                    if 20000 <= val <= 300000:
                        salaries.append(val)
                except (TypeError, ValueError):
                    pass

    salary_bins = {"< $50k": 0, "$50k-$100k": 0, "$100k-$150k": 0, "> $150k": 0}
    has_salaries = False
    for s in salaries:
        has_salaries = True
        if s < 50000: salary_bins["< $50k"] += 1
        elif s < 100000: salary_bins["$50k-$100k"] += 1
        elif s < 150000: salary_bins["$100k-$150k"] += 1
        else: salary_bins["> $150k"] += 1
        
    exp_bins = {"Junior": 0, "Mid-Level": 0, "Senior": 0, "Lead/Principal": 0}
    for title in df['position'].dropna():
        t = title.lower()
        if 'junior' in t or 'jr' in t: exp_bins["Junior"] += 1
        elif 'senior' in t or 'sr' in t: exp_bins["Senior"] += 1
        elif 'lead' in t or 'principal' in t or 'head' in t or 'director' in t: exp_bins["Lead/Principal"] += 1
        else: exp_bins["Mid-Level"] += 1
    exp_bins = {k: v for k, v in exp_bins.items() if v > 0}
    
    work_bins = {"Remote": 0, "Hybrid": 0, "On-site": 0}
    for _, row in df.iterrows():
        pos = str(row.get('position', '')).lower()
        loc = str(row.get('location', '')).lower()
        desc_text = str(row.get('description', '')).lower()
        if 'remote' in pos or 'remote' in loc or 'remote' in desc_text:
            work_bins["Remote"] += 1
        elif 'hybrid' in pos or 'hybrid' in loc or 'hybrid' in desc_text:
            work_bins["Hybrid"] += 1
        else:
            work_bins["On-site"] += 1
    work_bins = {k: v for k, v in work_bins.items() if v > 0}

    TECH_WORDS = set(config.TECH_WORDS)
    kw_counter = Counter()
    for desc in df['description'].dropna():
        words = set(re.findall(r'\b[a-z0-9+#]{2,15}\b', str(desc).lower()))
        for w in words:
            if w in TECH_WORDS:
                kw_counter[w] += 1
    top_keywords = {k.capitalize(): v for k, v in kw_counter.most_common(7)}

    return jsonify({
        "locations": loc_counts,
        "companies": comp_counts,
        "salaries": salary_bins if has_salaries else None,
        "experience": exp_bins,
        "work_type": work_bins,
        "keywords": top_keywords,
        "sources": sources,
        "total_jobs": len(df)
    })


@app.route("/download")
def download():
    csv_path = config.FINAL_CSV
    if not csv_path.exists():
        return "No results yet", 404
    return send_file(str(csv_path), as_attachment=True, download_name="jobs.csv")


def _run_scraper_background(parsed, task_id):
    """Run the scraper in a background thread with progress tracking."""
    # Setup logger for this task
    logger = setup_task_logger(task_id, _logs_dict)

    def is_cancelled():
        return task_id in _cancel_flags

    try:
        run_scraper(parsed, task_id=task_id, cancel_check=is_cancelled)
        
        if is_cancelled():
            logger.info("Process cancelled by user.")
            return

        process_jobs(parsed, task_id=task_id)

        if is_cancelled():
            return

        # Count results
        import pandas as pd
        count = 0
        if config.FINAL_CSV.exists():
            try:
                count = len(pd.read_csv(config.FINAL_CSV))
            except pd.errors.EmptyDataError:
                count = 0

        _set_status(task_id, "done", result_count=count)

    except Exception as e:
        logger.error(f"Failed with error: {str(e)}")
        _set_status(task_id, "error", error=str(e))


def start_ui(port: int = 8080, no_browser: bool = False):
    """Start the web UI server."""
    url = f"http://localhost:{port}"
    print(f"\n{'=' * 50}")
    print(f"  🌐 Job Scraper UI")
    print(f"  Відкрийте у браузері: {url}")
    print(f"  Для зупинки натисніть Ctrl+C")
    print(f"{'=' * 50}\n")

    if not no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    app.run(host="127.0.0.1", port=port, debug=False)
