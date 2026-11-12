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
        "security": [r"security|cyber|pentest|\bsoc\b|\biam\b|\bsiem\b"],
        "erp": [r"oracle (?:ebs|fusion|hcm|erp|cloud)|workday|\berp\b|\bcrm\b|\bsap\b|netsuite|dynamics 365|salesforce|odoo|hubspot|servicenow"],
        "data": [r"\bmdm\b|master data|\bdata\b|\bbi\b|business intelligence|power bi|tableau|database|\bdba\b|\betl\b|analytics|\bsql\b|"
                 r"snowflake|databricks|data warehouse"],
        "cloud": [r"cloud|devops|devsecops|\bsre\b|kubernetes|\baws\b|azure|\bgcp\b|platform engineer|infrastructure|"
                  r"observability|datadog|terraform"],
        "software": [r"software|\bjava\b|python|\.net\b|\bphp\b|react|angular|node\.?js|golang|\bruby\b|\bios\b|android|"
                     r"mobile app|embedded|c\+\+|typescript|javascript"],
        "it": [r"\bit\b|helpdesk|help desk|service desk|desktop support|m365|microsoft 365|active directory|intune|"
               r"\bict\b|application support|technical support|tech support|sysadmin|network|windows|linux|server"],
        "tech": [r"technical|\btech\b|systems?\b(?! analyst)|hardware|platform|integration"],
        "ecommerce": [r"e-?commerce|marketplace|amazon|shopify|online store"],
        "industrial": [r"\bplc\b|scada|industrial|mechanical|electrical|maintenance|automotive|hvac|process engineer|"
                       r"\br&d\b|mechatronic"],
        "construction": [r"construction|\bcivil\b|structural|site engineer"],
        "manufacturing": [r"production|manufactur|factory|assembly|\bcnc\b"],
        "logistics": [r"logistic|supply chain|warehouse(?! (?:engineer|developer|architect))|transport|shipping|freight|"
                      r"procurement|purchas|\bimport\b|\bexport\b|fleet"],
        "hr": [r"\bhr\b|human resources|\bpeople\b|talent|payroll|recruit"],
        "finance": [r"financ|revenue|\bcost\b|accounting|\bbank|insurance|\btax\b|audit|billing|invoic|credit|treasury|payment|fintech"],
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
