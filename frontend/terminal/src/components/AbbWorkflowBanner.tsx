import React from 'react';
import {Box, Text} from 'ink';

import type {AbbWorkflowSnapshot} from '../types.js';

export function AbbWorkflowBanner({
	workflow,
}: {
	workflow?: AbbWorkflowSnapshot | null;
}): React.JSX.Element | null {
	if (!workflow) {
		return null;
	}

	return (
		<Box
			flexDirection="row"
			alignItems="center"
			paddingX={1}
			marginBottom={1}
			borderStyle="round"
			borderColor="cyan"
		>
			<Text color="cyan" bold>
				🧭 ROUTE:{' '}
			</Text>
			<Text color="white" bold>
				{workflow.path}
			</Text>
			{workflow.title ? (
				<Text dimColor>
					{' '}({workflow.title})
				</Text>
			) : null}
		</Box>
	);
}
