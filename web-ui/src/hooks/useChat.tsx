import { useState, useEffect, useRef, useCallback, cloneElement, isValidElement } from 'react';
import { chatWithBookmarks } from '../api/client';
import type { ChatMessage, ChatSource } from '../api/client';
import type { Bookmark } from '../components/mypage/types';
import { CHAT_STORAGE_KEY } from '../components/mypage/types';

export function useChat(
  bookmarks: Bookmark[],
  chatBookmarkIds: string[],
  handleSelectBookmark: (bm: Bookmark) => Promise<unknown>,
) {
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    try {
      const saved = sessionStorage.getItem(CHAT_STORAGE_KEY);
      return saved ? JSON.parse(saved) : [];
    } catch { return []; }
  });
  const [inputValue, setInputValue] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [_pendingSources, setPendingSources] = useState<ChatSource[] | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Highlight terms for evidence highlighting in report
  const [highlightTerms, setHighlightTerms] = useState<string[]>([]);
  const [scrollToHighlight, setScrollToHighlight] = useState(false);

  const pendingSourcesRef = useRef<ChatSource[] | null>(null);

  // ── Effects ──

  // Persist chat history
  useEffect(() => {
    try { sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(messages)); } catch { /* ignore */ }
  }, [messages]);

  // Auto-scroll
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  // ── Helpers ──

  const extractHighlightTerms = (chatContent: string, refNum: number): string[] => {
    const citationPattern = `[${refNum}]`;
    const idx = chatContent.indexOf(citationPattern);
    if (idx === -1) return [];

    const before = chatContent.substring(Math.max(0, idx - 400), idx);
    const after = chatContent.substring(idx + citationPattern.length, Math.min(chatContent.length, idx + citationPattern.length + 300));

    const dotSpace = before.lastIndexOf('. ');
    const dotNewline = before.lastIndexOf('.\n');
    const doubleNewline = before.lastIndexOf('\n\n');
    const sentStart = Math.max(
      dotSpace >= 0 ? dotSpace + 2 : 0,
      dotNewline >= 0 ? dotNewline + 2 : 0,
      doubleNewline >= 0 ? doubleNewline + 2 : 0,
      0
    );
    const sentEndOffset = after.search(/[.!?]\s|[.!?]$|\n\n|。|！|？/);
    const sentEnd = sentEndOffset >= 0 ? sentEndOffset + 1 : after.length;

    const sentence = (before.substring(sentStart) + after.substring(0, sentEnd))
      .replace(/\[\d+\]/g, '')
      .replace(/[*_#>`~]/g, '')
      .trim();

    if (!sentence || sentence.length < 3) return [];

    const stopWords = new Set([
      'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had', 'her',
      'was', 'one', 'our', 'out', 'has', 'have', 'been', 'from', 'with', 'they',
      'this', 'that', 'these', 'those', 'which', 'their', 'also', 'more', 'some',
      'than', 'into', 'each', 'such', 'does', 'most', 'both', 'when', 'what',
      'about', 'between', 'through', 'using', 'based', 'other', 'where', 'while',
      'there', 'being', 'would', 'could', 'should', 'above', 'below',
    ]);

    const koStopWords = new Set([
      '있습니다', '합니다', '됩니다', '입니다', '습니다', '것입니다',
      '하는', '되는', '있는', '없는', '같은', '대한', '통해', '위해',
      '에서', '으로', '에게', '까지', '부터', '처럼', '만큼',
      '그리고', '하지만', '그러나', '따라서', '또한', '즉',
    ]);

    const terms: string[] = [];
    const seen = new Set<string>();
    const tokens = sentence.split(/\s+/);
    for (const raw of tokens) {
      if (terms.length >= 10) break;
      const w = raw.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, '');
      if (!w) continue;
      const lower = w.toLowerCase();
      const isKorean = /[\u3131-\uD79D]/.test(w);
      if (isKorean) {
        if (w.length >= 2 && !koStopWords.has(w) && !seen.has(w)) {
          seen.add(w);
          terms.push(w);
        }
      } else {
        if (w.length >= 4 && !stopWords.has(lower) && !seen.has(lower)) {
          seen.add(lower);
          terms.push(w);
        }
      }
    }
    return terms;
  };

  // ── Handlers ──

  const handleSendMessage = useCallback(async (overrideContent?: string) => {
    const trimmed = (overrideContent || inputValue).trim();
    if (!trimmed || isStreaming) return;

    const userMessage: ChatMessage = { role: 'user', content: trimmed };
    const updatedMessages = [...messages, userMessage];
    setMessages(updatedMessages);
    setInputValue('');
    setIsStreaming(true);
    setStreamingContent('');
    setPendingSources(null);
    pendingSourcesRef.current = null;

    let accumulated = '';

    await chatWithBookmarks(
      updatedMessages,
      chatBookmarkIds,
      (chunk) => {
        accumulated += chunk;
        setStreamingContent(accumulated);
      },
      (sources) => {
        pendingSourcesRef.current = sources;
        setPendingSources(sources);
      },
      () => {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: accumulated,
          sources: pendingSourcesRef.current || undefined,
        }]);
        setStreamingContent('');
        setPendingSources(null);
        pendingSourcesRef.current = null;
        setIsStreaming(false);
      },
      (error) => {
        setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${error}` }]);
        setStreamingContent('');
        setPendingSources(null);
        pendingSourcesRef.current = null;
        setIsStreaming(false);
      },
    );
  }, [inputValue, isStreaming, messages, chatBookmarkIds]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  }, [handleSendMessage]);

  const handleCitationClick = useCallback(async (source: ChatSource, chatContent: string, refNum: number) => {
    const bm = bookmarks.find(b => b.id === source.id);
    if (!bm) return;

    let terms = extractHighlightTerms(chatContent, refNum);
    if (terms.length === 0 && source.title) {
      const titleWords = source.title.split(/\s+/)
        .map(w => w.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, ''))
        .filter(w => w.length >= 3);
      terms = titleWords.slice(0, 6);
    }

    setHighlightTerms(terms);
    if (terms.length > 0) {
      setScrollToHighlight(true);
    }

    await handleSelectBookmark(bm);
  }, [bookmarks, handleSelectBookmark]);

  const clearChat = useCallback(() => {
    setMessages([]);
    sessionStorage.removeItem(CHAT_STORAGE_KEY);
  }, []);

  // ── Highlight text utilities (for report highlighting from citations) ──

  const highlightText = useCallback((text: string): React.ReactNode => {
    if (!highlightTerms.length) return text;
    const escaped = highlightTerms.map(t =>
      t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    );
    const pattern = new RegExp(`(${escaped.join('|')})`, 'gi');
    const parts = text.split(pattern);
    if (parts.length === 1) return text;
    let hlKey = 0;
    return parts.map((part, i) => {
      if (i % 2 === 1) {
        return <mark key={`hl-${hlKey++}`} className="mypage-highlight">{part}</mark>;
      }
      return part;
    });
  }, [highlightTerms]);

  const highlightChildren = useCallback((children: React.ReactNode): React.ReactNode => {
    if (!highlightTerms.length) return children;
    const processNode = (node: React.ReactNode, idx: number): React.ReactNode => {
      if (typeof node === 'string') return highlightText(node);
      if (isValidElement(node)) {
        const processed = highlightChildren((node.props as Record<string, unknown>).children as React.ReactNode);
        return cloneElement(node, { key: node.key || `hc-${idx}` }, processed);
      }
      return node;
    };
    if (Array.isArray(children)) return children.map((child, i) => processNode(child, i));
    return processNode(children, 0);
  }, [highlightTerms, highlightText]);

  // Render citation badges inline
  const renderCitationText = useCallback((text: string, sources?: ChatSource[], msgContent?: string) => {
    if (!sources || sources.length === 0) return <>{text}</>;
    const fullContent = msgContent || '';
    const parts: (string | React.ReactElement)[] = [];
    let lastIndex = 0;
    const regex = /\[(\d+)\]/g;
    let match;
    let key = 0;
    while ((match = regex.exec(text)) !== null) {
      if (match.index > lastIndex) parts.push(text.substring(lastIndex, match.index));
      const refNum = parseInt(match[1]);
      const source = sources.find(s => s.ref === refNum);
      if (source) {
        const capturedSource = source;
        const capturedRefNum = refNum;
        const capturedContent = fullContent;
        parts.push(
          <span
            key={`c-${key++}`}
            className="mypage-citation-badge"
            onClick={(e) => {
              e.stopPropagation();
              handleCitationClick(capturedSource, capturedContent, capturedRefNum);
            }}
            title={source.title}
          >[{refNum}]</span>
        );
      } else {
        parts.push(match[0]);
      }
      lastIndex = match.index + match[0].length;
    }
    if (lastIndex < text.length) parts.push(text.substring(lastIndex));
    return <>{parts}</>;
  }, [handleCitationClick]);

  const processCitationChildren = useCallback((children: React.ReactNode, sources?: ChatSource[], msgContent?: string): React.ReactNode => {
    const processNode = (node: React.ReactNode, idx: number): React.ReactNode => {
      if (typeof node === 'string') {
        return renderCitationText(node, sources, msgContent);
      }
      if (isValidElement(node) && (node.props as Record<string, unknown>).children) {
        const processed = processCitationChildren((node.props as Record<string, unknown>).children as React.ReactNode, sources, msgContent);
        return cloneElement(node, { key: node.key || `cn-${idx}` }, processed);
      }
      return node;
    };
    if (Array.isArray(children)) return children.map((child, i) => processNode(child, i));
    return processNode(children, 0);
  }, [renderCitationText]);

  return {
    // State
    messages, inputValue, setInputValue,
    isStreaming, streamingContent,
    highlightTerms, setHighlightTerms,
    scrollToHighlight, setScrollToHighlight,
    chatEndRef,
    // Handlers
    handleSendMessage, handleKeyDown,
    handleCitationClick, clearChat,
    // Utilities
    highlightChildren, processCitationChildren,
  };
}
