"""Seed canonical skills + their aliases (Phase B1 / Item 6 modernization).

Populates the existing `skills` and `skill_aliases` tables so the scoring
engine resolves "python3" / "Python 3.12" / "Py" to a single canonical token
before comparing must/nice skills.

Idempotent — uses ON CONFLICT DO NOTHING. Safe to re-run after schema reset
or to add new entries.

Run:
    python -m scripts.seed_skill_aliases --commit         # write rows
    python -m scripts.seed_skill_aliases --dry-run        # show what would happen

Source: top IT skills appearing in NEXUS prod data (Traffit imports + manual
job postings). Curated to avoid false equivalences ("Java" vs "JavaScript").
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.skill import Skill, SkillAlias  # noqa: E402

logger = logging.getLogger("seed_skill_aliases")

# {category: {canonical: [aliases...]}}.
# Aliases stored lowercase for stable matching (canonical_name kept Title-cased
# for display). Be conservative — never alias across distinct technologies.
SKILL_TAXONOMY: dict[str, dict[str, list[str]]] = {
    "language": {
        "Python": ["python", "python3", "python 3", "py", "py3"],
        "JavaScript": ["javascript", "js", "java script", "ecmascript", "es6", "es2015", "es2020"],
        "TypeScript": ["typescript", "ts"],
        "Java": ["java", "java se", "java ee", "core java", "j2ee", "jee"],
        "C#": ["c#", "csharp", "c sharp", "dot net c#"],
        "C++": ["c++", "cpp", "cplusplus"],
        "C": ["c"],
        "Go": ["go", "golang", "go lang"],
        "Rust": ["rust", "rustlang"],
        "Ruby": ["ruby", "rb"],
        "PHP": ["php"],
        "Kotlin": ["kotlin"],
        "Scala": ["scala"],
        "Swift": ["swift"],
        "Objective-C": ["objective-c", "objective c", "objc"],
        "Perl": ["perl"],
        "R": ["r", "r lang", "rlang"],
        "Lua": ["lua"],
        "Bash": ["bash", "shell", "sh", "shell script", "bash script"],
        "PowerShell": ["powershell", "ps1"],
        "SQL": ["sql"],
        "PL/SQL": ["pl/sql", "plsql"],
        "T-SQL": ["t-sql", "tsql", "transact-sql"],
        "Haskell": ["haskell"],
        "Elixir": ["elixir"],
        "Erlang": ["erlang"],
        "Dart": ["dart"],
        "Solidity": ["solidity"],
    },
    "frontend": {
        "React": ["react", "reactjs", "react.js", "react js"],
        "Vue.js": ["vue", "vuejs", "vue.js", "vue3", "vue 3"],
        "Angular": ["angular", "angularjs", "angular.js", "angular 2+", "ng"],
        "Next.js": ["next", "nextjs", "next.js"],
        "Nuxt.js": ["nuxt", "nuxtjs", "nuxt.js"],
        "Svelte": ["svelte", "sveltekit"],
        "jQuery": ["jquery"],
        "HTML": ["html", "html5"],
        "CSS": ["css", "css3"],
        "Sass": ["sass", "scss"],
        "Tailwind CSS": ["tailwind", "tailwindcss", "tailwind css"],
        "Bootstrap": ["bootstrap"],
        "Material UI": ["material ui", "mui", "material-ui"],
        "Webpack": ["webpack"],
        "Vite": ["vite"],
        "Redux": ["redux"],
        "RxJS": ["rxjs"],
    },
    "backend": {
        "Node.js": ["node", "nodejs", "node.js"],
        "Express.js": ["express", "expressjs", "express.js"],
        "NestJS": ["nestjs", "nest.js"],
        "Django": ["django"],
        "Flask": ["flask"],
        "FastAPI": ["fastapi", "fast api", "fast-api"],
        "Spring": ["spring", "spring framework"],
        "Spring Boot": ["spring boot", "springboot", "spring-boot"],
        "Hibernate": ["hibernate"],
        ".NET": [".net", "dotnet", "dot net", "asp.net core"],
        "ASP.NET": ["asp.net", "aspnet", "asp net"],
        "Laravel": ["laravel"],
        "Symfony": ["symfony"],
        "Ruby on Rails": ["ruby on rails", "rails", "ror"],
        "GraphQL": ["graphql", "graph ql"],
        "REST API": ["rest", "rest api", "restful", "restful api"],
        "gRPC": ["grpc", "g rpc"],
        "WebSocket": ["websocket", "websockets", "ws"],
        "Microservices": ["microservices", "microservice", "micro services"],
    },
    "database": {
        "PostgreSQL": ["postgresql", "postgres", "pg"],
        "MySQL": ["mysql"],
        "MariaDB": ["mariadb"],
        "Oracle DB": ["oracle", "oracle db", "oracledb"],
        "Microsoft SQL Server": ["mssql", "ms sql", "sql server", "microsoft sql"],
        "MongoDB": ["mongodb", "mongo"],
        "Redis": ["redis"],
        "Elasticsearch": ["elasticsearch", "elastic search", "es"],
        "Cassandra": ["cassandra"],
        "DynamoDB": ["dynamodb", "dynamo db"],
        "SQLite": ["sqlite", "sqlite3"],
        "Snowflake": ["snowflake"],
        "BigQuery": ["bigquery", "big query"],
        "Redshift": ["redshift", "amazon redshift"],
        "ClickHouse": ["clickhouse", "click house"],
        "Neo4j": ["neo4j"],
    },
    "devops": {
        "Docker": ["docker"],
        "Kubernetes": ["kubernetes", "k8s", "kube"],
        "Helm": ["helm"],
        "Terraform": ["terraform"],
        "Ansible": ["ansible"],
        "Puppet": ["puppet"],
        "Chef": ["chef"],
        "Jenkins": ["jenkins"],
        "GitLab CI": ["gitlab ci", "gitlabci", "gitlab-ci"],
        "GitHub Actions": ["github actions", "gh actions", "github-actions"],
        "CircleCI": ["circleci", "circle ci"],
        "Argo CD": ["argo cd", "argocd"],
        "Prometheus": ["prometheus"],
        "Grafana": ["grafana"],
        "ELK Stack": ["elk", "elk stack", "elastic stack"],
        "Datadog": ["datadog", "data dog"],
        "Linux": ["linux"],
        "Nginx": ["nginx"],
        "Apache HTTPD": ["apache", "apache httpd", "httpd"],
    },
    "cloud": {
        "AWS": ["aws", "amazon web services", "amazon aws"],
        "Azure": ["azure", "microsoft azure", "ms azure"],
        "GCP": ["gcp", "google cloud", "google cloud platform"],
        "Cloudflare": ["cloudflare"],
        "Heroku": ["heroku"],
        "DigitalOcean": ["digitalocean", "digital ocean"],
        "AWS Lambda": ["aws lambda", "lambda"],
        "AWS S3": ["s3", "aws s3", "amazon s3"],
        "AWS EC2": ["ec2", "aws ec2"],
        "Azure Functions": ["azure functions"],
        "Google Cloud Run": ["cloud run", "gcp cloud run"],
    },
    "data": {
        "Apache Spark": ["spark", "apache spark", "pyspark"],
        "Apache Kafka": ["kafka", "apache kafka"],
        "Apache Airflow": ["airflow", "apache airflow"],
        "Hadoop": ["hadoop"],
        "dbt": ["dbt", "data build tool"],
        "Pandas": ["pandas"],
        "NumPy": ["numpy", "num py"],
        "TensorFlow": ["tensorflow", "tensor flow", "tf"],
        "PyTorch": ["pytorch", "py torch"],
        "scikit-learn": ["scikit-learn", "scikit learn", "sklearn"],
        "Power BI": ["power bi", "powerbi"],
        "Tableau": ["tableau"],
        "Looker": ["looker"],
    },
    "qa": {
        "Selenium": ["selenium"],
        "Cypress": ["cypress"],
        "Playwright": ["playwright"],
        "Jest": ["jest"],
        "Mocha": ["mocha"],
        "JUnit": ["junit"],
        "pytest": ["pytest", "py test"],
        "Cucumber": ["cucumber"],
        "Postman": ["postman"],
        "JMeter": ["jmeter", "j meter", "apache jmeter"],
    },
    "mobile": {
        "Android": ["android"],
        "iOS": ["ios"],
        "React Native": ["react native", "react-native"],
        "Flutter": ["flutter"],
        "Xamarin": ["xamarin"],
        "Jetpack Compose": ["jetpack compose", "compose"],
    },
    "methodology": {
        "Agile": ["agile"],
        "Scrum": ["scrum"],
        "Kanban": ["kanban"],
        "SAFe": ["safe", "scaled agile framework"],
        "TDD": ["tdd", "test driven development", "test-driven development"],
        "BDD": ["bdd", "behavior driven development", "behaviour driven development"],
        "DDD": ["ddd", "domain driven design", "domain-driven design"],
        "CI/CD": ["ci/cd", "cicd", "ci-cd", "continuous integration"],
    },
    "security": {
        "OAuth": ["oauth", "oauth2", "oauth 2.0"],
        "OpenID Connect": ["openid", "openid connect", "oidc"],
        "JWT": ["jwt", "json web token"],
        "SAML": ["saml"],
        "OWASP": ["owasp"],
        "Penetration Testing": ["pentesting", "penetration testing", "pen testing"],
    },
}


async def _run(commit: bool) -> int:
    inserted_skills = 0
    inserted_aliases = 0
    skipped = 0

    async with AsyncSessionLocal() as db:
        for category, skills in SKILL_TAXONOMY.items():
            for canonical, aliases in skills.items():
                # 1) Insert canonical Skill (or fetch existing).
                existing = await db.scalar(
                    select(Skill).where(Skill.canonical_name == canonical)
                )
                if existing is None:
                    if commit:
                        stmt = (
                            pg_insert(Skill)
                            .values(canonical_name=canonical, category=category)
                            .on_conflict_do_nothing(index_elements=["canonical_name"])
                            .returning(Skill.id)
                        )
                        skill_id = await db.scalar(stmt)
                        if skill_id is None:
                            # Race: another worker inserted between SELECT and INSERT.
                            skill_id = await db.scalar(
                                select(Skill.id).where(Skill.canonical_name == canonical)
                            )
                        inserted_skills += 1
                    else:
                        logger.info("[dry] would insert Skill %s/%s", category, canonical)
                        skill_id = -1  # placeholder so alias loop runs
                else:
                    skill_id = existing.id

                # 2) Insert aliases (alias is UNIQUE → ON CONFLICT DO NOTHING).
                for alias in aliases:
                    alias_lc = alias.lower().strip()
                    if commit and skill_id is not None and skill_id > 0:
                        stmt = (
                            pg_insert(SkillAlias)
                            .values(skill_id=skill_id, alias=alias_lc)
                            .on_conflict_do_nothing(index_elements=["alias"])
                        )
                        result = await db.execute(stmt)
                        if result.rowcount and result.rowcount > 0:
                            inserted_aliases += 1
                        else:
                            skipped += 1
                    else:
                        logger.info("[dry] would insert alias %s -> %s", alias_lc, canonical)

        if commit:
            await db.commit()

    logger.info(
        "Done. skills_inserted=%s aliases_inserted=%s aliases_skipped=%s",
        inserted_skills,
        inserted_aliases,
        skipped,
    )
    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--commit", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if not args.commit and not args.dry_run:
        p.error("must pass --commit or --dry-run")
    if args.commit and args.dry_run:
        p.error("--commit and --dry-run are mutually exclusive")
    return args


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()
    return asyncio.run(_run(args.commit))


if __name__ == "__main__":
    sys.exit(main())
