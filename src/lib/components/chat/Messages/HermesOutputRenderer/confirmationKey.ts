import type { ConfirmationItem } from './types';

export function confirmationKey(item: ConfirmationItem): string {
	// No-id exec approvals are normalized to an empty confirmation_id. Fall back
	// to the persisted output item id so simultaneous no-id cards in the same run
	// do not collide while keeping frontend state keyed to the rendered item.
	return item.confirmation_id || `${item.run_id}:${item.id}`;
}
