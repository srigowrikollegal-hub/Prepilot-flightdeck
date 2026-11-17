"""PrepPilot knowledge base: skill taxonomy, verified question bank and learning resources.

Everything the agents ground their answers in lives here, so scores and plans are
repeatable and every interview question has a source id.
"""
import re
from urllib.parse import quote_plus

# skill id -> (display name, regex aliases)
SKILLS = {
    "python": ("Python", [r"\bpython\b"]),
    "java": ("Java", [r"\bjava\b(?!\s*script)"]),
    "cpp": ("C++", [r"c\+\+", r"\bcpp\b"]),
    "javascript": ("JavaScript", [r"\bjavascript\b", r"\bjs\b", r"\bnode\.?js\b", r"\breact\b"]),
    "sql": ("SQL", [r"\bsql\b", r"\bmysql\b", r"\bpostgres", r"\bqueries\b"]),
    "dbms": ("DBMS", [r"\bdbms\b", r"\bdatabase", r"\bnormali[sz]ation\b", r"\brdbms\b"]),
    "oop": ("OOP", [r"\boops?\b", r"object[- ]oriented"]),
    "dsa": ("Data Structures & Algorithms", [r"\bdsa\b", r"data structures?", r"\balgorithms?\b", r"\bleetcode\b"]),
    "os": ("Operating Systems", [r"operating systems?", r"\bos\b concepts", r"\bos\b(?=[,/ ])", r"\blinux\b"]),
    "cn": ("Computer Networks", [r"computer networks?", r"\bnetworking\b", r"\btcp/?ip\b", r"\bcn\b"]),
    "cloud": ("Cloud", [r"\bcloud\b", r"\baws\b", r"\bazure\b", r"\bgcp\b"]),
    "git": ("Git", [r"\bgit\b", r"\bgithub\b", r"version control"]),
    "ml": ("Machine Learning", [r"machine learning", r"\bml\b", r"scikit", r"\bxgboost\b"]),
    "dl_nlp": ("Deep Learning / NLP", [r"deep learning", r"\bnlp\b", r"\bllms?\b", r"neural network", r"tensorflow", r"pytorch"]),
    "web": ("HTML / CSS", [r"\bhtml5?\b", r"\bcss3?\b"]),
    "api": ("REST APIs", [r"\brest\b", r"\bapis?\b", r"\bfastapi\b", r"\bflask\b"]),
    "testing": ("Software Testing", [r"\btesting\b", r"unit tests?", r"\bselenium\b"]),
    "sdlc": ("SDLC / Agile", [r"\bsdlc\b", r"\bagile\b", r"\bscrum\b"]),
    "aptitude": ("Aptitude", [r"\baptitude\b", r"logical reasoning", r"quantitative"]),
    "communication": ("Communication", [r"communication", r"team ?work", r"interpersonal"]),
}

def skill_name(sid):
    return SKILLS.get(sid, (sid,))[0]

def extract_skills(text):
    t = (text or "").lower()
    found = []
    for sid, (_, pats) in SKILLS.items():
        if any(re.search(p, t) for p in pats):
            found.append(sid)
    return found

# Question bank: id, skill, level (1 easy, 2 medium, 3 hard), question, key points
QUESTIONS = [
    ("OOP-1", "oop", 1, "What are the four pillars of object oriented programming?",
     ["encapsulation", "abstraction", "inheritance", "polymorphism"]),
    ("OOP-2", "oop", 2, "What is the difference between method overloading and method overriding?",
     ["overloading same name different parameters", "compile time", "overriding subclass redefines parent method", "runtime polymorphism"]),
    ("OOP-3", "oop", 3, "Explain abstract class versus interface. When would you use each?",
     ["abstract class can have state and implemented methods", "interface is a contract", "multiple interfaces can be implemented", "use abstract class for shared base code"]),
    ("DBMS-1", "dbms", 1, "What is a primary key and how is it different from a foreign key?",
     ["primary key uniquely identifies a row", "not null and unique", "foreign key references primary key of another table", "maintains referential integrity"]),
    ("DBMS-2", "dbms", 2, "What is normalization? Explain 1NF, 2NF and 3NF.",
     ["reduce redundancy", "1nf atomic values", "2nf no partial dependency", "3nf no transitive dependency"]),
    ("DBMS-3", "dbms", 3, "What are ACID properties in a transaction?",
     ["atomicity all or nothing", "consistency", "isolation concurrent transactions", "durability survives failure"]),
    ("SQL-1", "sql", 1, "What is the difference between WHERE and HAVING?",
     ["where filters rows before grouping", "having filters groups after group by", "having used with aggregate functions"]),
    ("SQL-2", "sql", 2, "Explain INNER JOIN, LEFT JOIN and RIGHT JOIN.",
     ["inner join matching rows in both tables", "left join all rows from left table", "right join all rows from right table", "null for missing matches"]),
    ("SQL-3", "sql", 3, "How would you find the second highest salary from an Employee table?",
     ["max salary less than max", "subquery", "order by desc limit offset", "dense_rank"]),
    ("OS-1", "os", 1, "What is the difference between a process and a thread?",
     ["process independent program in execution", "own memory space", "thread lightweight unit inside process", "threads share memory"]),
    ("OS-2", "os", 2, "What is a deadlock? What are its four necessary conditions?",
     ["processes wait for each other forever", "mutual exclusion", "hold and wait", "no preemption", "circular wait"]),
    ("OS-3", "os", 3, "Explain paging and virtual memory.",
     ["memory divided into fixed size pages and frames", "page table maps pages to frames", "virtual memory uses disk as extension", "page fault"]),
    ("CN-1", "cn", 1, "Name the layers of the OSI model.",
     ["physical", "data link", "network", "transport", "session", "presentation", "application"]),
    ("CN-2", "cn", 2, "What is the difference between TCP and UDP?",
     ["tcp connection oriented", "reliable ordered delivery", "udp connectionless", "udp faster no guarantee", "udp for streaming"]),
    ("CN-3", "cn", 3, "What happens when you type a URL in the browser and press Enter?",
     ["dns lookup to get ip", "tcp connection handshake", "tls for https", "http request and response", "browser renders html"]),
    ("DSA-1", "dsa", 1, "What is the difference between an array and a linked list?",
     ["array contiguous memory", "index access o(1)", "linked list nodes with pointers", "insertion deletion easier in linked list"]),
    ("DSA-2", "dsa", 2, "Explain how binary search works and its time complexity.",
     ["sorted array", "compare with middle element", "discard half each step", "o(log n)"]),
    ("DSA-3", "dsa", 3, "When would you use a hash map, and what is a collision?",
     ["key value lookup average o(1)", "hash function maps key to index", "collision two keys same index", "chaining or open addressing"]),
    ("PY-1", "python", 1, "What is the difference between a list and a tuple in Python?",
     ["list mutable", "tuple immutable", "tuple can be dictionary key", "tuple slightly faster"]),
    ("PY-2", "python", 2, "What are decorators in Python?",
     ["function that wraps another function", "adds behaviour without changing code", "@ syntax", "example logging or timing"]),
    ("PY-3", "python", 3, "Explain shallow copy versus deep copy.",
     ["shallow copy copies outer object only", "nested objects shared", "deep copy copies everything recursively", "copy module"]),
    ("JAVA-1", "java", 1, "What is the difference between JDK, JRE and JVM?",
     ["jvm runs bytecode", "jre jvm plus libraries", "jdk jre plus development tools compiler", "platform independence"]),
    ("JAVA-2", "java", 2, "Why are strings immutable in Java?",
     ["string pool", "security", "thread safety", "hashcode caching"]),
    ("JS-1", "javascript", 1, "What is the difference between let, const and var?",
     ["var function scoped", "let and const block scoped", "const cannot be reassigned", "hoisting"]),
    ("JS-2", "javascript", 2, "What is a Promise and how does async/await help?",
     ["represents future value", "pending fulfilled rejected", "then catch", "async await makes asynchronous code read like synchronous"]),
    ("CLOUD-1", "cloud", 1, "What are IaaS, PaaS and SaaS? Give one example of each.",
     ["iaas infrastructure virtual machines ec2", "paas platform to deploy apps", "saas ready software gmail", "shared responsibility"]),
    ("CLOUD-2", "cloud", 2, "What is the difference between scaling up and scaling out?",
     ["vertical scaling bigger machine", "horizontal scaling more machines", "load balancer", "scale out more fault tolerant"]),
    ("GIT-1", "git", 1, "What is the difference between git merge and git rebase?",
     ["merge creates merge commit", "keeps history", "rebase replays commits on top", "linear history"]),
    ("ML-1", "ml", 1, "What is overfitting and how can you prevent it?",
     ["model memorises training data", "poor on unseen data", "regularization", "cross validation", "more data or dropout"]),
    ("ML-2", "ml", 2, "Explain precision, recall and F1 score.",
     ["precision true positives over predicted positives", "recall true positives over actual positives", "f1 harmonic mean", "trade off"]),
    ("DL-1", "dl_nlp", 2, "What is a transformer and why is attention useful?",
     ["attention weighs importance of each token", "self attention", "parallel processing unlike rnn", "basis of llms"]),
    ("DL-2", "dl_nlp", 2, "What is Retrieval-Augmented Generation (RAG)?",
     ["retrieve relevant documents", "add to prompt as context", "reduces hallucination", "up to date knowledge"]),
    ("WEB-1", "web", 1, "What is the CSS box model?",
     ["content", "padding", "border", "margin"]),
    ("API-1", "api", 1, "What is a REST API? Name the common HTTP methods.",
     ["stateless client server", "resources identified by urls", "get post put delete", "json responses status codes"]),
    ("TEST-1", "testing", 1, "What is the difference between unit testing and integration testing?",
     ["unit tests single function in isolation", "integration tests modules together", "unit faster", "both automated"]),
    ("SDLC-1", "sdlc", 1, "What is Agile and how is it different from Waterfall?",
     ["iterative sprints", "continuous feedback", "waterfall sequential phases", "agile flexible to change"]),
    ("APT-1", "aptitude", 1, "A train 150 m long crosses a pole in 10 seconds. What is its speed in km/h? Explain your steps.",
     ["speed distance over time", "15 m/s", "multiply by 18/5", "54 km/h"]),
    ("HR-1", "communication", 1, "Tell me about yourself.",
     ["name and education", "key skills", "project or achievement", "why this role"]),
    ("HR-2", "communication", 2, "Describe a time you faced a conflict in a team and how you resolved it.",
     ["situation", "task", "action you took", "result", "what you learned"]),
    ("HR-3", "communication", 2, "Why should we hire you?",
     ["match skills to role", "proof from project", "willingness to learn", "value to team"]),
]

QUESTION_BY_ID = {q[0]: q for q in QUESTIONS}

def questions_for(skill):
    return [q for q in QUESTIONS if q[1] == skill]

def yt(q):
    return "https://www.youtube.com/results?search_query=" + quote_plus(q)

# skill -> list of (title, url, kind)
RESOURCES = {
    "python": [("Python official tutorial", "https://docs.python.org/3/tutorial/", "docs"),
               ("CodeWithHarry Python (Hindi)", yt("codewithharry python one shot"), "video")],
    "java": [("Java one shot (Hindi)", yt("apna college java one shot"), "video")],
    "cpp": [("C++ one shot (Hindi)", yt("apna college c++ one shot"), "video")],
    "javascript": [("MDN JavaScript Guide", "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide", "docs"),
                   ("JavaScript one shot (Hindi)", yt("javascript one shot hindi"), "video")],
    "sql": [("SQL one shot (Hindi)", yt("apna college sql one shot"), "video"),
            ("SQLBolt interactive lessons", "https://sqlbolt.com/", "practice")],
    "dbms": [("Gate Smashers DBMS (Hindi)", yt("gate smashers dbms playlist"), "video")],
    "oop": [("OOPs one shot (Hindi)", yt("oops one shot hindi"), "video")],
    "dsa": [("Striver A2Z DSA sheet", "https://takeuforward.org/strivers-a2z-dsa-course/strivers-a2z-dsa-course-sheet-2", "practice"),
            ("LeetCode", "https://leetcode.com/problemset/", "practice")],
    "os": [("Gate Smashers Operating Systems (Hindi)", yt("gate smashers operating system playlist"), "video")],
    "cn": [("Gate Smashers Computer Networks (Hindi)", yt("gate smashers computer networks playlist"), "video")],
    "cloud": [("AWS Cloud Practitioner Essentials", "https://aws.amazon.com/training/digital/aws-cloud-practitioner-essentials/", "course"),
              ("Cloud computing basics (Hindi)", yt("cloud computing tutorial hindi"),"video")],
    "git": [("Git and GitHub one shot (Hindi)", yt("apna college git github"), "video"),
            ("Pro Git book", "https://git-scm.com/book/en/v2", "docs")],
    "ml": [("Krish Naik Machine Learning (Hindi)", yt("krish naik machine learning hindi playlist"), "video")],
    "dl_nlp": [("Deep Learning and NLP (Hindi)", yt("campusx deep learning playlist"), "video")],
    "web": [("MDN Learn web development", "https://developer.mozilla.org/en-US/docs/Learn", "docs")],
    "api": [("FastAPI tutorial", "https://fastapi.tiangolo.com/tutorial/", "docs")],
    "testing": [("Software testing tutorial (Hindi)", yt("software testing tutorial hindi"), "video")],
    "sdlc": [("SDLC and Agile (Hindi)", yt("sdlc agile model hindi gate smashers"), "video")],
    "aptitude": [("IndiaBIX aptitude practice", "https://www.indiabix.com/aptitude/questions-and-answers/", "practice"),
                 ("Aptitude for placements (Hindi)", yt("aptitude for placements hindi"), "video")],
    "communication": [("HR interview questions and answers", yt("hr interview questions and answers for freshers"), "video")],
}

SAMPLE_JD = """Systems Engineer (Freshers 2027) - Infosys, Bengaluru

We are looking for engineering graduates to join as Systems Engineers.
Requirements:
- Strong programming fundamentals in Python or Java
- Object oriented programming (OOP) concepts
- Data structures and algorithms
- DBMS and SQL queries
- Operating systems and computer networks basics
- Exposure to cloud platforms (AWS / Azure) is a plus
- Good aptitude and logical reasoning
- Good communication and teamwork skills
Selection: online test (aptitude, reasoning, coding), technical interview, HR interview."""

SAMPLE_RESUME = """K R Srigowri
B.E. Information Science, DSATM Bengaluru (2027)

Skills: Python, SQL, Machine Learning, Data Structures, Git, HTML, CSS
Projects:
- Dyslexia risk screening with machine learning: XGBoost model on 3,644 children,
  FastAPI backend, login and database, deployed on Render.
- PrepPilot: agentic AI placement assistant using Gemini function calling and Streamlit.
Coursework: DBMS, Operating Systems, Deep Learning and NLP, LLM and Agentic AI
Achievements: Amazon ML Challenge 2026 participant; Infosys System Engineer selection."""
