import React from 'react';
import {Box, Text} from 'ink';

export function AbbModeBadge({
	mode,
}: {
	mode?: string | null;
}): React.JSX.Element {
	const normalized = (mode ?? 'agent').toLowerCase();

	if (normalized === 'plan' || normalized === 'plan mode') {
		return (
			<Box marginRight={1}>
				<Text backgroundColor="cyan" color="black" bold>
					{' 📐 PLAN '}
				</Text>
			</Box>
		);
	}

	if (normalized === 'ask') {
		return (
			<Box marginRight={1}>
				<Text backgroundColor="magenta" color="white" bold>
					{' 💬 ASK '}
				</Text>
			</Box>
		);
	}

	return (
		<Box marginRight={1}>
			<Text backgroundColor="green" color="black" bold>
				{' ⚡ AGENT '}
			</Text>
		</Box>
	);
}
