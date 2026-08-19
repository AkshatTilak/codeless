import React from 'react';
import {Box, Text} from 'ink';

import type {AbbDagSnapshot, AbbTaskSnapshot} from '../types.js';

export function AbbDagPanel({
	dag,
}: {
	dag?: AbbDagSnapshot | null;
}): React.JSX.Element | null {
	if (!dag || (!dag.base_tasks.length && !dag.subtasks.length)) {
		return null;
	}

	const goalTitle = (dag.goal?.title as string) || (dag.goal?.id as string) || 'System Goal';
	const goalStatus = (dag.goal?.status as string) || 'in_progress';

	return (
		<Box flexDirection="column" borderStyle="round" borderColor="blue" paddingX={1} marginBottom={1}>
			<Box flexDirection="row" justifyContent="space-between">
				<Text bold color="blueBright">
					🎯 {goalTitle}
				</Text>
				<Text dimColor>[{goalStatus}]</Text>
			</Box>

			<Box flexDirection="column" marginTop={1}>
				{dag.base_tasks.map((base) => {
					const subtasksForBase = dag.subtasks.filter((s) => s.parent === base.id);
					return (
						<Box key={base.id} flexDirection="column" marginBottom={1}>
							<Box flexDirection="row">
								<Text bold color={base.status === 'done' ? 'green' : base.status === 'in_progress' ? 'yellow' : 'white'}>
									{base.status === 'done' ? '✅' : base.status === 'in_progress' ? '⏳' : '⏸️'}{' '}
									{base.id}
								</Text>
								{base.title ? <Text dimColor> — {base.title}</Text> : null}
							</Box>

							{subtasksForBase.length > 0 ? (
								<Box flexDirection="column" paddingLeft={3}>
									{subtasksForBase.map((sub) => (
										<SubtaskRow key={sub.id} subtask={sub} isActive={dag.active_subtask_id === sub.id} />
									))}
								</Box>
							) : null}
						</Box>
					);
				})}
			</Box>
		</Box>
	);
}

function SubtaskRow({
	subtask,
	isActive,
}: {
	subtask: AbbTaskSnapshot;
	isActive: boolean;
}): React.JSX.Element {
	const badge = subtask.status === 'done'
		? '[x]'
		: subtask.status === 'in_progress'
		? '[/]'
		: subtask.dependencies_satisfied === false
		? '[!]'
		: '[ ]';

	const color = subtask.status === 'done'
		? 'green'
		: subtask.status === 'in_progress'
		? 'cyan'
		: subtask.dependencies_satisfied === false
		? 'red'
		: 'gray';

	const deps = subtask.depends_on && subtask.depends_on.length > 0
		? ` (deps: ${subtask.depends_on.join(', ')})`
		: '';

	return (
		<Box flexDirection="row">
			<Text color={color} bold={isActive}>
				{badge} {subtask.id}
			</Text>
			{subtask.title ? <Text dimColor> {subtask.title}</Text> : null}
			{deps ? <Text dimColor color="yellow">{deps}</Text> : null}
			{isActive ? <Text color="cyan" bold> {'<-- ACTIVE'}</Text> : null}
		</Box>
	);
}
