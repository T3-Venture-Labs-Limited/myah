"""Load composition definitions from installed skills.

Each skill can declare compositions in a `composable/` directory as YAML files.
This module scans those directories and registers compositions with the global
registry so they're available to the agent at runtime.

Example skill structure:
    skills/email_skill/
    ├── composable/
    │   ├── thread_view.yaml  → name: email_thread, template: {blocks: [...]}
    │   └── compose_form.yaml → name: email_compose, template: {blocks: [...]}
"""

import logging
from pathlib import Path
from typing import Optional

import yaml

from open_webui.utils.agui_compositions import registry

logger = logging.getLogger(__name__)


def load_skill_compositions(skills_dir: Optional[str] = None) -> int:
    """Scan skills directory and register all compositions found.

    Args:
        skills_dir: Path to skills directory. Defaults to the platform skills dir.

    Returns:
        Number of compositions registered.
    """
    if skills_dir is None:
        from open_webui.env import DATA_DIR

        skills_dir = str(Path(DATA_DIR) / 'skills')

    skills_path = Path(skills_dir)
    if not skills_path.exists():
        logger.debug(f'Skills directory does not exist: {skills_dir}')
        return 0

    registered_count = 0
    for skill_dir in skills_path.iterdir():
        if not skill_dir.is_dir():
            continue
        composable_dir = skill_dir / 'composable'
        if not composable_dir.exists():
            continue

        for yaml_file in composable_dir.glob('*.yaml'):
            try:
                with open(yaml_file) as f:
                    composition_def = yaml.safe_load(f)
                name = composition_def.get('name')
                template = composition_def.get('template')
                if not name or not template:
                    logger.warning(f'Skipping {yaml_file}: missing "name" or "template"')
                    continue
                registry.register(name, template)
                logger.info(
                    f'Loaded composition "{name}" from skill {skill_dir.name}',
                    extra={'skill': skill_dir.name, 'composition': name},
                )
                registered_count += 1
            except Exception as e:
                logger.warning(f'Failed to load composition from {yaml_file}: {e}', exc_info=True)

    logger.info(f'Loaded {registered_count} skill compositions from {skills_dir}')
    return registered_count
