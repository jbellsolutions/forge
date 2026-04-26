"""forge — model-agnostic, self-learning, self-healing agent harness.

Public SDK surface — import from here for the canonical API.
Subpackages (forge.kernel, forge.swarm, forge.memory, forge.tools, forge.healing,
forge.skills, forge.observability, forge.providers, forge.recursion) remain the
authoritative homes for each layer; this top-level module is a convenience
re-export.
"""
from . import _dotenv  # noqa: F401  -- side-effect: load ~/.forge/.env

__version__ = "0.1.0"

# L0 kernel
from .kernel import (
    AgentDef,
    AgentLoop,
    AssistantTurn,
    HookBus,
    HookContext,
    LoopResult,
    Message,
    PermissionMode,
    ProviderProfile,
    ToolCall,
    ToolResult,
    Verdict,
    load_profile,
)

# L1 memory
from .memory import (
    ClaudeDir,
    GitJournal,
    Memory,
    Note,
    ObsidianVault,
    PromotionResult,
    ReasoningBank,
    genome,
    genome_path,
    promote,
)

# L2 tools
from .tools import Tool, ToolRegistry

# L3 healing
from .healing import (
    CircuitBreaker,
    CircuitRegistry,
    CircuitState,
    ErrorType,
    attach_healing,
    classify,
)

# L4 swarm
from .swarm import (
    Consensus,
    RoleAssignment,
    RoleCouncilSpawner,
    Spawner,
    SwarmResult,
    SwarmSpec,
    Topology,
)

# L5 skills
from .skills import (
    CONFIDENCE_MARGIN,
    EvalReport,
    MIN_SAMPLES,
    SkillRun,
    SkillSearchIndex,
    SkillStore,
    autosynth,
    evaluate,
    promote_if_passing,
)

# L7 observability
from .observability import SessionStat, Telemetry, TraceStore

# Providers
from .providers import Provider, make_provider

# Recursion
from .recursion import (
    HarnessDiff,
    RecurseResult,
    ResultsLedger,
    TraceAnalyzer,
    propose,
    propose_with_llm,
    recurse_once,
)


__all__ = [
    "__version__",
    # L0 kernel
    "AgentDef", "AgentLoop", "AssistantTurn", "HookBus", "HookContext",
    "LoopResult", "Message", "PermissionMode", "ProviderProfile", "ToolCall",
    "ToolResult", "Verdict", "load_profile",
    # L1 memory
    "ClaudeDir", "GitJournal", "Memory", "Note", "ObsidianVault",
    "PromotionResult", "ReasoningBank", "genome", "genome_path", "promote",
    # L2 tools
    "Tool", "ToolRegistry",
    # L3 healing
    "CircuitBreaker", "CircuitRegistry", "CircuitState", "ErrorType",
    "attach_healing", "classify",
    # L4 swarm
    "Consensus", "RoleAssignment", "RoleCouncilSpawner", "Spawner",
    "SwarmResult", "SwarmSpec", "Topology",
    # L5 skills
    "CONFIDENCE_MARGIN", "EvalReport", "MIN_SAMPLES", "SkillRun",
    "SkillSearchIndex", "SkillStore", "autosynth", "evaluate",
    "promote_if_passing",
    # L7 observability
    "SessionStat", "Telemetry", "TraceStore",
    # Providers
    "Provider", "make_provider",
    # Recursion
    "HarnessDiff", "RecurseResult", "ResultsLedger", "TraceAnalyzer",
    "propose", "propose_with_llm", "recurse_once",
]
