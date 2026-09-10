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
	// Primary key: tool_use_id (unique per invocation).
	// Fallback: tool_name (legacy events without tool_use_id).
	const pairedResultIndices = new Set<number>();

	for (let i = 0; i < items.length; i++) {
		const cur = items[i];
		if (cur.role === 'tool') {
			// Find the first matching unpaired tool_result for this tool
			let matchIdx = -1;
			for (let j = i + 1; j < items.length; j++) {
				if (items[j].role !== 'tool_result' || pairedResultIndices.has(j)) {
					if (items[j].role === 'assistant' || items[j].role === 'user') {
						break;
					}
					continue;
				}
				// Match by tool_use_id if both sides have it
				if (cur.tool_use_id && items[j].tool_use_id) {
					if (items[j].tool_use_id === cur.tool_use_id) {
						matchIdx = j;
						break;
					}
					continue;
				}
				// Fallback: match by tool_name (legacy compat)
				if (items[j].tool_name === cur.tool_name || !items[j].tool_name) {
					matchIdx = j;
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

/**
 * Estimate how many terminal lines a transcript item will consume when
 * rendered by Ink.  This is a heuristic — exact rendering depends on
 * markdown expansion and terminal font — but it keeps the view within
 * the physical terminal bounds and prevents ANSI scrollback overflow.
 */
function estimateItemLines(item: TranscriptItem | ToolPair, cols: number): number {
	if (Array.isArray(item)) {
		// Tool pair: header + summary + result lines
		const [toolItem, resultItem] = item as [TranscriptItem, TranscriptItem];
		const toolLines = Math.max(1, Math.ceil((toolItem.text?.length ?? 20) / cols));
		const resultLines = Math.max(1, Math.ceil((resultItem.text?.length ?? 20) / cols));
		return toolLines + resultLines + 2; // +2 for borders/spacing
	}
	const text = item.text ?? '';
	const lines = text.split('\n').length;
	// Account for line wrapping
	let wrappedLines = 0;
	for (const line of text.split('\n')) {
		wrappedLines += Math.max(1, Math.ceil((line.length || 1) / cols));
	}
	return Math.max(lines, wrappedLines) + 1; // +1 for role prefix / margin
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

	// Dynamic viewport windowing: only render items that fit within the
	// terminal's physical row count.  This prevents Ink's ANSI cursor-up
	// escape from clipping at row 1 and triggering continuous screen rewrites.
	const terminalRows = process.stdout.rows || 24;
	const terminalCols = process.stdout.columns || 80;
	// Reserve lines for header, status bar, prompt input, and keyboard hints
	const reservedLines = 6;
	const lineBudget = Math.max(8, terminalRows - reservedLines);

	// Walk items from newest to oldest, accumulating estimated line counts
	let usedLines = 0;
	let startIdx = items.length;
	for (let i = items.length - 1; i >= 0; i--) {
		const est = estimateItemLines(items[i], terminalCols);
		if (usedLines + est > lineBudget) {
			break;
		}
		usedLines += est;
		startIdx = i;
	}
	const visible = items.slice(startIdx);
	const grouped = groupToolPairs(visible);

	return (
		<Box flexDirection="column" flexGrow={1}>
			{showWelcome && items.length === 0 ? <WelcomeBanner /> : null}

			{grouped.map((group, index) => {
				if (Array.isArray(group)) {
					const [toolItem, resultItem] = group as [TranscriptItem, TranscriptItem];
					// Stable key: prefer tool_use_id, fall back to index-based key
					const stableKey = toolItem.tool_use_id ?? `tool-pair-${startIdx + index}`;
					return (
						<ToolCallDisplay
							key={stableKey}
							item={toolItem}
							resultItem={resultItem}
							outputStyle={outputStyle}
						/>
					);
				}
				const item = group as TranscriptItem;
				const stableKey = item.tool_use_id ?? `item-${item.role}-${startIdx + index}`;
				return (
					<MessageRow
						key={stableKey}
						item={item}
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
