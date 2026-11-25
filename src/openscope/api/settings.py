"""Runtime configuration, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_REPO_EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


def _paths(value: str | None) -> list[Path]:
    return [Path(p.strip()) for p in (value or "").split(",") if p.strip()]


@dataclass
class Settings:
    """
    OPENSCOPE_DB_URL        SQLAlchemy URL            (default: sqlite:///./openscope.db)
    OPENSCOPE_DATASETS      bundled factor datasets   (default: desnz-2025,useeio-1.3)
    OPENSCOPE_FACTOR_FILES  extra factor CSVs, comma-separated
    OPENSCOPE_RULE_FILES    extra classification rule CSVs, comma-separated
    OPENSCOPE_DEMO_DIR      folder with demo data     (default: the repo's examples/)
    OPENSCOPE_STATIC_DIR    built Angular app to serve at /
    OPENSCOPE_LLM           "1" to allow Claude classification (needs ANTHROPIC_API_KEY)
    OPENSCOPE_LLM_MODEL     model id                  (default: claude-opus-5-5)
    OPENSCOPE_CORS_ORIGINS  comma-separated origins for local frontend development
    OPENSCOPE_PUBLIC_DEMO   "1" for a public demo: loads demo data at startup and shows a
                            banner warning visitors that data is public and temporary
    """

    db_url: str = "sqlite:///./openscope.db"
    datasets: list[str] = field(default_factory=lambda: ["desnz-2025", "useeio-1.3"])
    factor_files: list[Path] = field(default_factory=list)
    rule_files: list[Path] = field(default_factory=list)
    demo_dir: Path | None = None
    static_dir: Path | None = None
    llm_enabled: bool = False
    llm_model: str = "claude-opus-5-5"
    public_demo: bool = False
    cors_origins: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        demo_env = env.get("OPENSCOPE_DEMO_DIR")
        demo_dir = (
            Path(demo_env) if demo_env else (_REPO_EXAMPLES if _REPO_EXAMPLES.is_dir() else None)
        )
        s = cls(
            db_url=env.get("OPENSCOPE_DB_URL", cls.db_url),
            datasets=[
                d.strip()
                for d in env.get("OPENSCOPE_DATASETS", "desnz-2025,useeio-1.3").split(",")
                if d.strip()
            ],
            factor_files=_paths(env.get("OPENSCOPE_FACTOR_FILES")),
            rule_files=_paths(env.get("OPENSCOPE_RULE_FILES")),
            demo_dir=demo_dir,
            static_dir=Path(env["OPENSCOPE_STATIC_DIR"])
            if env.get("OPENSCOPE_STATIC_DIR")
            else None,
            llm_enabled=env.get("OPENSCOPE_LLM") == "1",
            public_demo=env.get("OPENSCOPE_PUBLIC_DEMO") == "1",
            llm_model=env.get("OPENSCOPE_LLM_MODEL", cls.llm_model),
            cors_origins=[
                o.strip() for o in env.get("OPENSCOPE_CORS_ORIGINS", "").split(",") if o.strip()
            ],
        )
        s.add_demo_defaults()
        return s

    def add_demo_defaults(self) -> None:
        """When demo data is available, load its example classification rules too."""
        if self.demo_dir is None:
            return
        rules = self.demo_dir / "classification_rules_example.csv"
        if rules.is_file() and rules not in self.rule_files:
            self.rule_files.append(rules)
