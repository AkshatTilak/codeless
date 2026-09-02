import React from 'react';
import {Box, Text} from 'ink';

import {useTheme} from '../theme/ThemeContext.js';
import type {TranscriptItem} from '../types.js';
import {MarkdownText} from './MarkdownText.js';
import {ToolCallDisplay} from './ToolCallDisplay.js';
import {WelcomeBanner} from './WelcomeBanner.js';

type ToolPair = readonly [TranscriptItem, TranscriptItem];
type GroupedItem = TranscriptItem | ToolPair;

function groupToolPairs(items: TranscriptItem[]): GroupedItem[] {
	const result: GroupedItem[] = [];
	// Pair tools with tool_results even when multiple tools are dispatched in parallel
	// (e.g. tool1, tool2, tool_result1, tool_result2).
	const pairedResultIndices = new Set<number>();

	for (let i = 0; i < items.length; i++) {
		const cur = items[i];
		if (cur.role === 'tool') {
			// Find the first matching unpaired tool_result for this tool
			let matchIdx = -1;
			for (let j = i + 1; j < items.length; j++) {
				if (
					items[j].role === 'tool_result' &&
					!pairedResultIndices.has(j) &&
					(items[j].tool_name === cur.tool_name || !items[j].tool_name)
				) {
					matchIdx = j;
					break;
				}
				// If another assistant or user message intervenes, stop searching
				if (items[j].role === 'assistant' || items[j].role === 'user') {
					break;
				}
			}

			if (matchIdx !== -1) {
				pairedResultIndices.add(matchIdx);
				result.push([cur, items[matchIdx]] as const);
			} else {
				result.push(cur);
			}
		} else if (cur.role === 'tool_result') {
			if (!pairedResultIndices.has(i)) {
				result.push(cur);
			}
		} else {
			result.push(cur);
		}
	}
	return result;
}

function ConversationViewInner({
	items,
	assistantBuffer,
	showWelcome,
	outputStyle,
}: {
	items: TranscriptItem[];
	assistantBuffer: string;
	showWelcome: boolean;
	outputStyle: string;
}): React.JSX.Element {
	const {theme} = useTheme();
	const isCodexStyle = outputStyle === 'codex';
	const visible = items.slice(-40);
	const grouped = groupToolPairs(visible);

	return (
		<Box flexDirection="column" flexGrow={1}>
			{showWelcome && items.length === 0 ? <WelcomeBanner /> : null}

			{grouped.map((group, index) => {
				if (Array.isArray(group)) {
					const [toolItem, resultItem] = group as [TranscriptItem, TranscriptItem];
					return (
						<ToolCallDisplay
							key={index}
							item={toolItem}
							resultItem={resultItem}
							outputStyle={outputStyle}
						/>
					);
				}
				return (
					<MessageRow
						key={index}
						item={group as TranscriptItem}
						theme={theme}
						outputStyle={outputStyle}
					/>
				);
			})}

			{assistantBuffer ? (
				isCodexStyle ? (
					<Box flexDirection="row" marginTop={0}>
						<Text>{assistantBuffer}</Text>
					</Box>
				) : (
					<Box marginTop={1} marginBottom={0} flexDirection="column">
						<Text>
							<Text color={theme.colors.success} bold>{theme.icons.assistant}</Text>
						</Text>
						<Box marginLeft={2} flexDirection="column">
							<MarkdownText content={assistantBuffer} />
						</Box>
					</Box>
				)
			) : null}
		</Box>
	);
}

export const ConversationView = React.memo(ConversationViewInner);

function MessageRow({
	item,
	theme,
	outputStyle,
}: {
	item: TranscriptItem;
	theme: ReturnType<typeof useTheme>['theme'];
	outputStyle: string;
}): React.JSX.Element {
	const isCodexStyle = outputStyle === 'codex';

	switch (item.role) {
		case 'user':
			if (isCodexStyle) {
				return (
					<Box marginTop={0}>
						<Text>
							<Text dimColor>{'> '}</Text>
							<Text>{item.text}</Text>
						</Text>
					</Box>
				);
			}
			return (
				<Box marginTop={1} marginBottom={0}>
					<Text>
						<Text color={theme.colors.secondary} bold>{theme.icons.user}</Text>
						<Text>{item.text}</Text>
					</Text>
				</Box>
			);

		case 'assistant':
			if (isCodexStyle) {
				return (
					<Box marginTop={0} marginBottom={0}>
						<Text>{item.text}</Text>
					</Box>
				);
			}
			return (
				<Box marginTop={1} marginBottom={0} flexDirection="column">
					<Text>
						<Text color={theme.colors.success} bold>{theme.icons.assistant}</Text>
					</Text>
					<Box marginLeft={2} flexDirection="column">
						<MarkdownText content={item.text} />
					</Box>
				</Box>
			);

		case 'tool':
		case 'tool_result':
			return <ToolCallDisplay item={item} outputStyle={outputStyle} />;

		case 'system':
			if (isCodexStyle) {
				return (
					<Box marginTop={0}>
						<Text>
							<Text color={theme.colors.warning}>[system]</Text>
							<Text> {item.text}</Text>
						</Text>
					</Box>
				);
			}
			return (
				<Box marginTop={0}>
					<Text>
						<Text color={theme.colors.warning}>{theme.icons.system}</Text>
						<Text color={theme.colors.warning}>{item.text}</Text>
					</Text>
				</Box>
			);

		case 'status':
			return (
				<Box marginTop={0}>
					<Text color={theme.colors.info}>{item.text}</Text>
				</Box>
			);

		case 'log':
			return (
				<Box>
					<Text dimColor>{item.text}</Text>
				</Box>
			);

		default:
			return (
				<Box>
					<Text>{item.text}</Text>
				</Box>
			);
	}
}
