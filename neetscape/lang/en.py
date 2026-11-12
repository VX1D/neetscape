"""English: used for every country (always the last pack) and alone for international boards."""

VOCAB = {
    "first": {
        "mode": [
            ("remote", r"fully remote|full[- ]remote|100\s*% remote|remote only|remote[- ]only"),
            ("remote", r"remote\s*(?:/|,|or)\s*hybrid|hybrid\s*(?:/|,|or)\s*remote"),  # a choice: remote is offered
        ],
    },
    "mode": {
        "remote": [r"\bremote\b", r"home office"],
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
    "hints": {
        "fully_remote": [r"fully remote", r"full-remote", r"remote-first", r"100% remote"],
        "hybrid": [r"hybrid\w*", r"on-?site", r"\d+ days (?:a week )?in (?:the )?office"],
        "years": [r"\d\+?\s*(?:-\s*\d+\s*)?years?\s*(?:of )?(?:commercial )?experience"],
        "degree": [r"bachelor\w*", r"master'?s", r"\bdegree\b"],
        "languages": [r"\b(?:german|french|dutch|italian|spanish|swedish|norwegian|danish|czech)\b"],
        "fixed_term": [r"fixed[- ]term", r"temporary contract"],
    },
}

EXAMPLES = [
    ("Fully remote Python developer", "mode", "remote"),
    ("Hybrid, 2 days in the office", "mode", "hybrid"),
    ("Hybrid work, 3 days remote per week", "mode", "hybrid"),
    ("Hybrid (2 days in the office), remote possible", "mode", "hybrid"),
    ("Remote or hybrid, your choice", "mode", "remote"),
    ("Remote DevOps engineer (hybrid cloud, AWS)", "mode", "remote"),
    ("On-site in Berlin", "mode", "onsite"),
    ("Part-time support agent", "worktime", "part_time"),
    ("Full-time, permanent contract", "contract", ["employment"]),
    ("Senior Data Engineer", "level", "senior"),
    ("Head of Support", "level", "lead"),
    ("3+ years of commercial experience", "years", True),
    ("12-month fixed-term contract", "fixed_term", True),
]
