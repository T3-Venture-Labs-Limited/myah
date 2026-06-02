export const ATTACH_MAX_AGGREGATE_BYTES = 80 * 1024 * 1024;

export type ComposerFileItem = {
	id?: string;
	name?: string;
	size?: number;
};

export type ComposerAttachStatus = 'attached' | 'duplicate' | 'too-large' | 'empty';

export type ComposerAttachResult = {
	status: ComposerAttachStatus;
	files: ComposerFileItem[];
	fileItem?: ComposerFileItem;
};

const fileSize = (file: ComposerFileItem | undefined | null): number =>
	typeof file?.size === 'number' && Number.isFinite(file.size) ? file.size : 0;

export const appendComposerFile = (
	currentFiles: ComposerFileItem[] = [],
	fileItem: ComposerFileItem | null | undefined
): ComposerAttachResult => {
	if (!fileItem) {
		return { status: 'empty', files: currentFiles };
	}

	const { id } = fileItem;
	if (id && currentFiles.some((file) => file.id === id)) {
		return { status: 'duplicate', files: currentFiles, fileItem };
	}

	const aggregate = currentFiles.reduce((sum, file) => sum + fileSize(file), 0);
	if (aggregate + fileSize(fileItem) > ATTACH_MAX_AGGREGATE_BYTES) {
		return { status: 'too-large', files: currentFiles, fileItem };
	}

	return { status: 'attached', files: [...currentFiles, fileItem], fileItem };
};

export const appendComposerFiles = (
	currentFiles: ComposerFileItem[] = [],
	fileItems: Array<ComposerFileItem | null | undefined> = []
): { files: ComposerFileItem[]; results: ComposerAttachResult[] } => {
	let files = currentFiles;
	const results: ComposerAttachResult[] = [];

	for (const fileItem of fileItems) {
		const result = appendComposerFile(files, fileItem);
		results.push(result);
		files = result.files;
	}

	return { files, results };
};
