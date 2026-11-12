"""English: used for every country (always the last pack) and alone for international boards."""

VOCAB = {
    "qualifier": [r"with", r"for"],  # words that open a title's qualifier ("Support Specialist with German")
    "gender": [r"all\s+genders?"],     # bracketed gender markers in words ("(all genders)")
    "explicit": {
        "contract": {
            "internship": [r"employment type:\s*internship"],  # a labelled field; free text says "staż"/"internship" for other reasons
        },
        "mode": {
            "remote": [
                r"fully remote|full[- ]remote|100\s*% remote|remote only|remote[- ]only",
                r"remote\s*(?:/|,|or)\s*hybrid|hybrid\s*(?:/|,|or)\s*remote",  # a choice: remote is offered
            ],
        },
    },
    "mode": {
        "remote": [r"\bremote\b", r"home office", r"work(?:ing)? from (?:your (?:own )?)?home"],
        "hybrid": [r"hybrid(?![- ](?:cloud|apps?|mobile|infrastructure|environments?))"],
        "onsite": [r"on-?site"],
    },
    "worktime": {
        "part_time": [r"part[- ]?time"],
        "flexible": [r"freelance", r"flexible hours", r"per task"],
        "full_time": [r"full[- ]?time"],
    },
    "contract": {
        "employment": [r"permanent", r"\bcoe\b"],
        "mandate": [r"mandate"],
        "internship": [r"internship"],
        "freelance": [r"freelance"],
    },
    "level": {
        "intern": [r"\bintern\b", r"trainee"],
        "junior": [r"junior", r"\bjr\b", r"entry[- ]level"],
        "senior": [r"senior", r"\bsr\b", r"expert"],
        "lead": [r"\blead\b", r"principal", r"staff", r"architect", r"head of"],
        "manager": [r"manager", r"director"],
        "mid": [r"\bmid\b", r"regular"],
    },
    "function": {
        "test": [r"\bqa\b|tester|testing|\btest (?:engineer|analyst|automation|specialist|lead|manager)|quality assurance|\bsdet\b"],
        "shop": [r"cashier|(?:sales|shop|store|retail) assistant|merchandiser"],
        "assist": [r"assistant|secretary|receptionist|clerk|data entry|back ?office|office (?:administrator|coordinator)"],
        "serve": [r"customer (?:support|service|care|success|experience|contact|onboarding)|client (?:service|support)|"
                  r"call ?cent|contact cent|helpline"],
        "sell": [r"\bsales\b|account (?:executive|manager)|business development|key account|telemarket|pre-?sales"],
        "people": [r"recruit|talent acquisition|sourcer|headhunt|payroll"],
        "teach": [r"teacher|tutor|lecturer|instructor|\btrainer\b"],
        "care": [r"nurse|caregiver|\bcarer\b|physician|doctor|dentist|therapist|pharmacist|paramedic"],
        "manage_project": [r"project (?:manager|coordinator|lead)|product (?:owner|manager)|scrum master|\bpmo\b|"
                           r"delivery manager|program(?:me)? manager|business analyst|systems? analyst"],
        "automate": [r"automation|\bautomat(?:e|ing)\b|\brpa\b|n8n|zapier|power automate"],
        "develop": [r"developer|programmer|\bcoder\b|front-?end|back-?end|full[- ]?stack|software engineer"],
        "design": [r"designer|\bux\b|\bui\b|graphic|illustrat"],
        "market": [r"marketing|\bseo\b|\bsem\b|social media|copywrit|content (?:creator|writer|manager|specialist)|"
                   r"community manager|\bpr\b"],
        "account": [r"accountant|accounting|bookkeep|controller|controlling|auditor|\btax\b"],
        "law": [r"lawyer|attorney|paralegal|legal counsel|solicitor|notary"],
        "transport": [r"driver|courier|forwarder|dispatcher|warehouse (?:worker|operative|associate)|\bpicker\b|forklift"],
        "cook_clean": [r"\bcook\b|\bchef\b|waiter|waitress|barista|bartender|housekeep|cleaner|cleaning|dishwasher"],
        "operate": [r"operator|assembler|machinist|welder|production worker|packer"],
        "build": [r"electrician|mechanic|plumber|installer|fitter|carpenter|bricklayer"],
        "administer": [r"administrator|\badmin\b|sysadmin"],
        "support": [r"support|helpdesk|help desk|service desk"],
        "analyse": [r"analyst|analytics|scientist"],
        "consult": [r"consultant|advis[eo]r"],
        "engineer": [r"engineer|technician|architect"],
        "manage": [r"manager|head of|director|\blead\b|coordinator|supervisor|team leader"],
        "specialist": [r"specialist|expert|officer|associate"],
    },
    "domain": {
        "ai": [r"\bai\b|\bllms?\b|gen ?ai|artificial intelligence|machine learning|\bml\b|deep learning|\bnlp\b|"
               r"computer vision|copilot|\bprompt|chatbot|annotat|\brater\b|evaluator|ai train"],
        "security": [r"\bidentity\b|security|cyber|pentest|\bsoc\b|\biam\b|\bsiem\b"],
        "erp": [r"oracle (?:ebs|fusion|hcm|erp|cloud)|workday|\berp\b|\bcrm\b|\bsap\b|netsuite|dynamics 365|salesforce|odoo|hubspot|servicenow"],
        "data": [r"\bmdm\b|master data|\bdata\b|\bbi\b|business intelligence|power bi|tableau|database|\bdba\b|\betl\b|analytics|\bsql\b|"
                 r"snowflake|databricks|data warehouse"],
        "cloud": [r"reliability|cloud|devops|devsecops|\bsre\b|kubernetes|\baws\b|azure|\bgcp\b|platform engineer|infrastructure|"
                  r"observability|datadog|terraform"],
        "software": [r"full[- ]?stack|back-?end|front-?end|software|\bjava\b|python|\.net\b|\bphp\b|react|angular|node\.?js|golang|\bruby\b|\bios\b|android|"
                     r"mobile app|embedded|c\+\+|typescript|javascript"],
        "it": [r"integrat\w*|systems? analyst|jira|atlassian|confluence|\bit\b|helpdesk|help desk|service desk|desktop support|m365|microsoft 365|active directory|intune|"
               r"\bict\b|application support|technical support|tech support|sysadmin|network(?:ing| (?:engineer|administrator|admin|support|security|specialist|technician))|windows|linux|server"],
        "tech": [r"technical|\btech\b|systems?\b(?! analyst)|hardware|platform"],
        "ecommerce": [r"e-?commerce|marketplace|amazon|shopify|online store"],
        "industrial": [r"\bplc\b|scada|industrial|mechanical|electrical|maintenance|automotive|hvac|process engineer|"
                       r"\br&d\b|mechatronic"],
        "construction": [r"construction|\bcivil\b|structural|site engineer"],
        "manufacturing": [r"production|manufactur|factory|assembly|\bcnc\b"],
        "logistics": [r"logistic|supply chain|warehouse(?! (?:engineer|developer|architect))|transport|shipping|freight|"
                      r"procurement|purchas|\bimport\b|\bexport\b|fleet"],
        "hr": [r"\bhr\b|human resources|\bpeople\b|talent|payroll|recruit"],
        "finance": [r"accountant|financ|revenue|\bcost\b|accounting|\bbank|insurance|\btax\b|audit|billing|invoic|credit|treasury|payment|fintech"],
        "legal": [r"legal|compliance|gdpr|regulatory|privacy"],
        "health": [r"medical|clinical|health|pharma|patient|hospital|dental|nursing"],
        "education": [r"education|school|teaching|e-?learning|academy"],
        "hospitality": [r"hotel|restaurant|hospitality|kitchen|catering"],
        "retail": [r"retail|\bstore\b|\bshop\b|boutique"],
        "customer": [r"customer|\bclient\b"],
        "sales": [r"\bsales\b|commercial"],
        "marketing": [r"marketing|\bbrand|\bmedia\b|content|\bseo\b"],
        "office": [r"\boffice\b|administrative"],
        "design": [r"design|creative"],
        "product": [r"\bproduct\b|\bproject\b"],
    },
    # pay text (neetscape/pay.py): units of time, pay words, the thousand suffix, the word between two amounts
    "choice": [r"\b(?:or|either)\b", r"remote/", r"/hybrid"],
    "placeholder_companies": ["confidential", "anonymous"],
    "pay": {
        "hour": [r"/\s*h\b", r"/\s*hour", r"hourly", r"/\s*hr\b", r"per hour"],
        "week": [r"/\s*week\b", r"per week"],
        "day": [r"/\s*day", r"daily", r"per day"],
        "year": [r"/\s*year", r"/\s*yr\b", r"annual", r"yearly"],
        "words": [r"gross", r"\bnet\b", r"salary"],
        "thousand": [r"k"],
        "range": [r"to"],
    },
    "hints": {
        "fully_remote": [r"fully[- ]remote", r"full-remote", r"100\s*% remote", r"remote[- ]only", r"work from anywhere",
                         r"from anywhere in (?:poland|europe|the eu)"],
        "hybrid": [r"hybrid\w*", r"on-?site", r"\d+ days (?:a week )?in (?:the )?office"],
        "years": [r"\d\+?\s*(?:-\s*\d+\s*)?years?\s*(?:of )?(?:commercial )?experience"],
        "degree": [r"bachelor\w*", r"master'?s", r"\bdegree\b"],
        "languages": [r"\b(?:german|french|dutch|italian|spanish|swedish|norwegian|danish|czech)\b"],
        "fixed_term": [r"fixed[- ]term", r"temporary contract"],
        "office": [r"client visits?", r"visits? (?:to|at) (?:the |our )?clients?", r"business trips?", r"travel(?:ling)? (?:is )?required",
                   r"willing(?:ness)? to travel", r"(?:once|twice|\d+ times?) (?:a|per) (?:month|week|quarter)\W+(?:in|at|to) (?:the |our )?office",
                   r"office (?:days?|visits?)", r"relocat\w*", r"on-?site onboarding"],
    },
}

# Interface of REPORT.html (optional; English is the fallback of every other language's missing keys).
# `{name}` is a placeholder; a dict keyed by CLDR plural category (one, few, many, other) is a plural chosen by `{n}`.
UI = {
    "name": "English",
    "review": "Review", "all": "All", "search": "Search  /",
    "g_auto": "Group: auto", "g_category": "Group: note category", "g_status": "Group: status", "g_tag": "Group: tag",
    "g_search": "Group: search", "g_board": "Group: board", "g_field": "Group: job field", "g_mode": "Group: work mode",
    "g_none": "No groups",
    "s_score": "Sort: score", "s_pay": "Sort: pay", "s_newest": "Sort: newest", "s_company": "Sort: company",
    "filters": "Filters", "any_mode": "Any work mode", "any_board": "Any board", "f_new": "New in this run",
    "f_posted": "With posting", "f_unreviewed": "Not decided", "f_hide": "Hide decided", "remote_only": "Remote only",
    "keys": "j/k move · o open · s/a/r/i decide · u undo · n note · / search",
    "empty": "Nothing here. Clear the filters.",
    "empty_review": 'No review yet: decide in "All" or record one with neetscape mark.',
    "select": "Select an offer.",
    "pay": "pay / month", "mode": "mode", "time": "time", "contract": "contract", "level": "level", "posted": "posted",
    "on": "on", "score": "score", "ago": "ago", "fully_remote": "fully remote", "dm": "domains",
    "open": "Open offer ↗", "back": "← list", "note_ph": "Note: why · risk (saved with the decision)", "clear": "Clear",
    "copy": {"one": "Copy {n} command", "other": "Copy {n} commands"},
    "copied": {"one": "Copied {n} command: paste them in the terminal", "other": "Copied {n} commands: paste them in the terminal"},
    "confirm_clear": "Forget the decisions made on this page?",
    "decided": "{a} / {b} decided", "more": "Show more ({n} left)", "shown": "{a} of {b}",
    "offers": {"one": "{n} offer", "other": "{n} offers"}, "new": "{n} new",
    "errors": {"one": "{n} board error", "other": "{n} board errors"},
    "cut": {"one": "{n} cut listing", "other": "{n} cut listings"},
    "p_none": "Posting not fetched", "p_empty": "Posting is empty", "p_failed": "Fetching the posting failed",
    "p_gone": "Offer removed", "p_http": "Posting unavailable",
    "other": "other", "no_tag": "no tag", "not_reviewed": "not reviewed",
    "view": "View", "prev": "Previous (k)", "next": "Next (j)", "lang": "Language",
    "st": {"shortlisted": "shortlisted", "applied": "applied", "interview": "interview", "offer": "offer",
           "rejected": "rejected", "ignored": "ignored"},
    "fd": {"ai_automation": "AI & automation", "security": "Security", "qa": "QA & testing", "devops_cloud": "DevOps & cloud",
           "data": "Data & analytics", "it_support": "IT support", "it_admin": "IT administration", "erp_crm": "ERP & CRM",
           "software_dev": "Software development", "product_project": "Product & project", "design": "Design",
           "ecommerce": "E-commerce", "customer_service": "Customer service", "sales": "Sales", "marketing": "Marketing",
           "hr": "HR & payroll", "finance": "Finance & accounting", "legal": "Legal", "admin_office": "Office & admin",
           "logistics": "Logistics", "engineering": "Engineering", "manufacturing": "Manufacturing",
           "healthcare": "Healthcare", "education": "Education", "hospitality": "Hospitality", "retail": "Retail",
           "other": "Other"},
    "md": {"remote": "remote", "hybrid": "hybrid", "onsite": "on-site", "unknown": "unknown"},
    "wt": {"full_time": "full time", "part_time": "part time", "flexible": "flexible"},
}
