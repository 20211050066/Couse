import os


os.environ["DATABASE_URL"] = (
    "postgresql+psycopg://course:123456@127.0.0.1:5432/course_agent_test"
)
os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/15"
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["RERANK_API_KEY"] = ""
