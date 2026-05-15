# Knowledge is a living thing — it grows inside the container,
# and we hold a faithful copy here so the UI never goes dark.

from pydantic import BaseModel, ConfigDict

# ── Pydantic response models ───────────────────────────────────────────────────


class AgentToolResponse(BaseModel):
    name: str
    description: str
    toolset: str
    emoji: str | None = None


class AgentToolsetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    name: str
    label: str
    emoji: str | None = None
    enabled: bool
    tools: list[AgentToolResponse] = []
    last_synced_at: int


class AgentSkillResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    name: str
    category: str
    description: str
    source: str
    trust: str
    last_synced_at: int


class AgentSkillDetailResponse(AgentSkillResponse):
    content: str


class AgentPluginResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    filename: str
    name: str
    description: str
    content: str
    last_synced_at: int


class AgentMcpServerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    name: str
    url: str | None = None
    command: str | None = None
    args: list[str] = []
    status: str
    last_synced_at: int


class AgentModelResponse(BaseModel):
    model: str


class AgentSoulResponse(BaseModel):
    content: str


# ── Request forms ──────────────────────────────────────────────────────────────


class AgentToolsetToggleForm(BaseModel):
    enabled: bool


class AgentSkillCreateForm(BaseModel):
    name: str
    category: str = 'general'
    description: str = ''
    trigger: str = ''
    content: str  # markdown body (without frontmatter)


class AgentSkillUpdateForm(BaseModel):
    name: str | None = None
    category: str | None = None
    description: str | None = None
    trigger: str | None = None
    content: str | None = None


class AgentPluginCreateForm(BaseModel):
    name: str
    description: str = ''
    content: str  # Python source


class AgentPluginUpdateForm(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None


class AgentMcpServerCreateForm(BaseModel):
    name: str
    url: str | None = None
    command: str | None = None
    args: list[str] = []
    api_key: str | None = None


class AgentModelUpdateForm(BaseModel):
    model: str


class AgentSoulUpdateForm(BaseModel):
    content: str


