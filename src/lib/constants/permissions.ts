export const DEFAULT_PERMISSIONS = {
	workspace: {
		models: false,
		tools: false,
		skills: false
	},
	sharing: {
		models: false,
		public_models: false,
		tools: false,
		public_tools: false,
		skills: false,
		public_skills: false,
		notes: false,
		public_notes: false
	},
	access_grants: {
		allow_users: true
	},
	chat: {
		controls: true,
		valves: true,
		system_prompt: true,
		params: true,
		file_upload: true,
		web_upload: true,
		delete: true,
		delete_message: true,
		continue_response: true,
		regenerate_response: true,
		rate_response: true,
		edit: true,
		share: true,
		export: true,
		temporary: true,
		temporary_enforced: false
	},
	features: {
		api_keys: false,
		notes: true,
		channels: true,
		folders: true,
		direct_tool_servers: false,
		web_search: true,
		image_generation: true,
		memories: true
	},
	settings: {
		interface: true
	}
} as const;
