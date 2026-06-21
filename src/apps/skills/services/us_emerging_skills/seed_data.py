from dataclasses import dataclass, field


@dataclass(frozen=True)
class EmergingSkillSeed:
    name: str
    category: str
    aliases: list[str] = field(default_factory=list)
    description: str = ""


CATEGORY_AI_ML = "AI / ML"
CATEGORY_DATA_ENGINEERING = "Data Engineering"
CATEGORY_CLOUD = "Cloud Computing"
CATEGORY_DEVOPS = "DevOps"

US_EMERGING_SKILLS: list[EmergingSkillSeed] = [
    # AI / LLM
    EmergingSkillSeed("LangChain", CATEGORY_AI_ML, ["Lang Chain"]),
    EmergingSkillSeed("LangGraph", CATEGORY_AI_ML),
    EmergingSkillSeed("LlamaIndex", CATEGORY_AI_ML, ["Llama Index"]),
    EmergingSkillSeed("DSPy", CATEGORY_AI_ML),
    EmergingSkillSeed("CrewAI", CATEGORY_AI_ML, ["Crew AI"]),
    EmergingSkillSeed("AutoGen", CATEGORY_AI_ML, ["Auto Gen", "Microsoft AutoGen"]),
    EmergingSkillSeed("Semantic Kernel", CATEGORY_AI_ML),
    EmergingSkillSeed("Prompt Engineering", CATEGORY_AI_ML),
    EmergingSkillSeed("Prompt Optimization", CATEGORY_AI_ML),
    EmergingSkillSeed("Prompt Evaluation", CATEGORY_AI_ML),
    EmergingSkillSeed("Agentic AI", CATEGORY_AI_ML, ["Agentic Artificial Intelligence"]),
    EmergingSkillSeed("AI Agents", CATEGORY_AI_ML, ["Artificial Intelligence Agents"]),
    EmergingSkillSeed("Multi-Agent Systems", CATEGORY_AI_ML, ["Multi Agent Systems"]),
    EmergingSkillSeed(
        "RAG",
        CATEGORY_AI_ML,
        ["Retrieval-Augmented Generation", "retrieval augmented generation"],
        "Retrieval-augmented generation for LLM applications.",
    ),
    EmergingSkillSeed("GraphRAG", CATEGORY_AI_ML, ["Graph RAG"]),
    EmergingSkillSeed("Hybrid Search", CATEGORY_AI_ML),
    EmergingSkillSeed("Fine Tuning", CATEGORY_AI_ML, ["Fine-Tuning", "Model Fine Tuning"]),
    EmergingSkillSeed("LoRA", CATEGORY_AI_ML, ["Low-Rank Adaptation"]),
    EmergingSkillSeed("PEFT", CATEGORY_AI_ML, ["Parameter-Efficient Fine Tuning"]),
    EmergingSkillSeed("RLHF", CATEGORY_AI_ML, ["Reinforcement Learning from Human Feedback"]),
    EmergingSkillSeed("Model Evaluation", CATEGORY_AI_ML),
    EmergingSkillSeed("LLM Evaluation", CATEGORY_AI_ML, ["Large Language Model Evaluation"]),
    EmergingSkillSeed("Benchmarking", CATEGORY_AI_ML, ["Model Benchmarking"]),
    EmergingSkillSeed(
        "LLM",
        CATEGORY_AI_ML,
        ["Large Language Models", "Large Language Model"],
        "Large language model technologies and applications.",
    ),
    EmergingSkillSeed("Vector Databases", CATEGORY_AI_ML, ["Vector DB", "Vector Database"]),
    EmergingSkillSeed("Embedding Models", CATEGORY_AI_ML, ["Text Embedding Models"]),
    EmergingSkillSeed("OpenAI API", CATEGORY_AI_ML, ["OpenAI APIs"]),
    EmergingSkillSeed("Claude API", CATEGORY_AI_ML, ["Anthropic Claude API"]),
    EmergingSkillSeed("Gemini API", CATEGORY_AI_ML, ["Google Gemini API"]),
    # Data Engineering
    EmergingSkillSeed("dbt", CATEGORY_DATA_ENGINEERING, ["data build tool"]),
    EmergingSkillSeed("Snowflake", CATEGORY_DATA_ENGINEERING),
    EmergingSkillSeed("Databricks", CATEGORY_DATA_ENGINEERING),
    EmergingSkillSeed("Delta Lake", CATEGORY_DATA_ENGINEERING),
    EmergingSkillSeed("Apache Iceberg", CATEGORY_DATA_ENGINEERING, ["Iceberg"]),
    EmergingSkillSeed("Apache Hudi", CATEGORY_DATA_ENGINEERING, ["Hudi"]),
    EmergingSkillSeed("Apache Spark", CATEGORY_DATA_ENGINEERING, ["Spark"]),
    EmergingSkillSeed("Apache Kafka", CATEGORY_DATA_ENGINEERING, ["Kafka"]),
    EmergingSkillSeed("Apache Airflow", CATEGORY_DATA_ENGINEERING, ["Airflow"]),
    EmergingSkillSeed("Data Modeling", CATEGORY_DATA_ENGINEERING),
    EmergingSkillSeed("Data Warehousing", CATEGORY_DATA_ENGINEERING),
    EmergingSkillSeed("ETL", CATEGORY_DATA_ENGINEERING, ["Extract Transform Load"]),
    EmergingSkillSeed("ELT", CATEGORY_DATA_ENGINEERING, ["Extract Load Transform"]),
    EmergingSkillSeed("Big Data", CATEGORY_DATA_ENGINEERING),
    EmergingSkillSeed("Streaming Analytics", CATEGORY_DATA_ENGINEERING),
    # Cloud
    EmergingSkillSeed("Terraform", CATEGORY_CLOUD, ["TF"]),
    EmergingSkillSeed("OpenTofu", CATEGORY_CLOUD, ["Open Tofu"]),
    EmergingSkillSeed("Pulumi", CATEGORY_CLOUD),
    EmergingSkillSeed("Amazon EKS", CATEGORY_CLOUD, ["AWS EKS", "EKS"]),
    EmergingSkillSeed("Amazon ECS", CATEGORY_CLOUD, ["AWS ECS", "ECS"]),
    EmergingSkillSeed("Azure AKS", CATEGORY_CLOUD, ["AKS", "Azure Kubernetes Service"]),
    EmergingSkillSeed("Google GKE", CATEGORY_CLOUD, ["GKE", "Google Kubernetes Engine"]),
    EmergingSkillSeed("Cloud Architecture", CATEGORY_CLOUD),
    EmergingSkillSeed(
        "Infrastructure as Code",
        CATEGORY_CLOUD,
        ["IaC", "Infrastructure-as-Code"],
    ),
    # DevOps
    EmergingSkillSeed("ArgoCD", CATEGORY_DEVOPS, ["Argo CD"]),
    EmergingSkillSeed("FluxCD", CATEGORY_DEVOPS, ["Flux CD", "Flux"]),
    EmergingSkillSeed("GitHub Actions", CATEGORY_DEVOPS),
    EmergingSkillSeed("GitLab CI", CATEGORY_DEVOPS, ["GitLab CI/CD"]),
    EmergingSkillSeed("Prometheus", CATEGORY_DEVOPS),
    EmergingSkillSeed("Grafana", CATEGORY_DEVOPS),
    EmergingSkillSeed("OpenTelemetry", CATEGORY_DEVOPS, ["OTel"]),
    EmergingSkillSeed("Kubernetes Operators", CATEGORY_DEVOPS, ["K8s Operators"]),
    EmergingSkillSeed("Observability", CATEGORY_DEVOPS),
    EmergingSkillSeed("Platform Engineering", CATEGORY_DEVOPS),
]

US_EMERGING_CATEGORIES: list[str] = [
    CATEGORY_AI_ML,
    CATEGORY_DATA_ENGINEERING,
    CATEGORY_CLOUD,
    CATEGORY_DEVOPS,
]
