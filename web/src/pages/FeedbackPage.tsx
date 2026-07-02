import { useState, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { format } from "date-fns";
import { zhCN } from "react-day-picker/locale";
import { withBasePath } from "../lib/basePath";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Skeleton } from "../components/ui/skeleton";
import { Calendar } from "../components/ui/calendar";
import { Popover, PopoverTrigger, PopoverContent } from "../components/ui/popover";
import { Download, CalendarIcon } from "lucide-react";
import { cn } from "../lib/utils";

interface FeedbackItem {
  session_key: string;
  message_id: string;
  role: string;
  message_content: string;
  issue_type: string;
  description: string;
  created_at: string;
}

const ISSUE_TYPE_LABELS: Record<string, string> = {
  wrong: "回答错误",
  outdated: "信息过时",
  tool_error: "工具调用失败",
  format: "格式问题",
  other: "其他",
};

const ISSUE_TYPES = Object.keys(ISSUE_TYPE_LABELS);
const PAGE_SIZE = 20;

export default function FeedbackPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [loading, setLoading] = useState(true);

  // Filters
  const [contentFilter, setContentFilter] = useState("");
  const [issueTypeFilter, setIssueTypeFilter] = useState("");
  const [descFilter, setDescFilter] = useState("");
  const [dateFrom, setDateFrom] = useState<Date | undefined>();
  const [dateTo, setDateTo] = useState<Date | undefined>();

  // Pagination
  const [page, setPage] = useState(1);

  const fetchFeedback = async () => {
    setLoading(true);
    try {
      const resp = await fetch(withBasePath("/api/chat/feedback"));
      if (resp.ok) {
        setItems(await resp.json());
      }
    } catch { /* ignore */ }
    setLoading(false);
  };

  const handleDelete = async (index: number) => {
    try {
      await fetch(withBasePath(`/api/chat/feedback/${index}`), { method: "DELETE" });
      fetchFeedback();
    } catch { /* ignore */ }
  };

  useEffect(() => { fetchFeedback(); }, []);

  // Sort by time descending + apply filters
  const filtered = useMemo(() => {
    const sorted = [...items].sort((a, b) =>
      (b.created_at ?? "").localeCompare(a.created_at ?? "")
    );
    return sorted.filter((item) => {
      if (contentFilter && !(item.message_content ?? "").toLowerCase().includes(contentFilter.toLowerCase())) return false;
      if (issueTypeFilter && item.issue_type !== issueTypeFilter) return false;
      if (descFilter && !(item.description ?? "").toLowerCase().includes(descFilter.toLowerCase())) return false;
      if (dateFrom) {
        if (new Date(item.created_at) < dateFrom) return false;
      }
      if (dateTo) {
        const to = new Date(dateTo);
        to.setDate(to.getDate() + 1); // include the full "to" day
        if (new Date(item.created_at) >= to) return false;
      }
      return true;
    });
  }, [items, contentFilter, issueTypeFilter, descFilter, dateFrom, dateTo]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const paged = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  // Reset to page 1 when filters change
  useEffect(() => { setPage(1); }, [contentFilter, issueTypeFilter, descFilter, dateFrom, dateTo]);

  const clearFilters = () => {
    setContentFilter("");
    setIssueTypeFilter("");
    setDescFilter("");
    setDateFrom(undefined);
    setDateTo(undefined);
  };

  const hasFilters = contentFilter || issueTypeFilter || descFilter || dateFrom || dateTo;

  const downloadExcel = () => {
    const headers = ["会话ID", "角色", "对话内容", "反馈问题", "补充说明", "提交时间"];
    const escapeCsv = (v: string) => `"${(v ?? "").replace(/"/g, '""')}"`;
    const rows = filtered.map((item) => [
      item.session_key,
      item.role,
      item.message_content ?? "",
      ISSUE_TYPE_LABELS[item.issue_type] || item.issue_type,
      item.description ?? "",
      new Date(item.created_at).toLocaleString(),
    ].map(escapeCsv).join(","));
    const csv = "﻿" + [headers.join(","), ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `反馈记录_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">对话反馈</h1>
        <Button size="sm" variant="outline" onClick={fetchFeedback}>刷新</Button>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-end gap-3 rounded-xl border bg-white px-4 py-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">对话内容</label>
          <Input
            value={contentFilter}
            onChange={(e) => setContentFilter(e.target.value)}
            placeholder="搜索内容..."
            className="h-8 w-44 text-xs"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">反馈问题</label>
          <select
            value={issueTypeFilter}
            onChange={(e) => setIssueTypeFilter(e.target.value)}
            className="h-8 w-32 rounded-md border border-input bg-white px-2 text-xs"
          >
            <option value="">全部</option>
            {ISSUE_TYPES.map((t) => (
              <option key={t} value={t}>{ISSUE_TYPE_LABELS[t]}</option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">补充说明</label>
          <Input
            value={descFilter}
            onChange={(e) => setDescFilter(e.target.value)}
            placeholder="搜索说明..."
            className="h-8 w-44 text-xs"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">开始日期</label>
          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                className={cn(
                  "h-8 w-36 justify-start text-left font-normal text-xs",
                  !dateFrom && "text-muted-foreground"
                )}
              >
                <CalendarIcon className="mr-1.5 h-3.5 w-3.5" />
                {dateFrom ? format(dateFrom, "yyyy-MM-dd") : "选择日期"}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <Calendar
                mode="single"
                selected={dateFrom}
                onSelect={setDateFrom}
                locale={zhCN}
              />
            </PopoverContent>
          </Popover>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">结束日期</label>
          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                className={cn(
                  "h-8 w-36 justify-start text-left font-normal text-xs",
                  !dateTo && "text-muted-foreground"
                )}
              >
                <CalendarIcon className="mr-1.5 h-3.5 w-3.5" />
                {dateTo ? format(dateTo, "yyyy-MM-dd") : "选择日期"}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <Calendar
                mode="single"
                selected={dateTo}
                onSelect={setDateTo}
                locale={zhCN}
              />
            </PopoverContent>
          </Popover>
        </div>
        {hasFilters && (
          <Button size="sm" variant="ghost" onClick={clearFilters} className="h-8 text-xs text-muted-foreground">
            清除筛选
          </Button>
        )}
        <Button size="sm" variant="outline" onClick={downloadExcel} className="h-8 text-xs gap-1" disabled={filtered.length === 0}>
          <Download className="h-3.5 w-3.5" />
          下载
        </Button>
      </div>

      {loading ? (
        <div className="space-y-2">{[...Array(5)].map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border bg-white py-12 text-center text-muted-foreground text-sm">
          {hasFilters ? "没有匹配的反馈记录" : "暂无反馈记录"}
        </div>
      ) : (
        <>
          <div className="rounded-xl border bg-white overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 text-left">
                  <th className="px-4 py-3 font-medium text-slate-600">会话ID</th>
                  <th className="px-4 py-3 font-medium text-slate-600">对话内容</th>
                  <th className="px-4 py-3 font-medium text-slate-600">反馈问题</th>
                  <th className="px-4 py-3 font-medium text-slate-600">补充说明</th>
                  <th className="px-4 py-3 font-medium text-slate-600">提交时间</th>
                  <th className="px-4 py-3 font-medium text-slate-600 w-16">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {paged.map((item, i) => {
                  const globalIndex = items.indexOf(item);
                  return (
                    <tr key={i} className="hover:bg-slate-50/50">
                      <td className="px-4 py-3">
                        {item.session_key ? (
                          <button
                            onClick={() => navigate(`/chat/${item.session_key}`)}
                            className="font-mono text-xs text-[#298c88] hover:underline hover:text-[#1d6b67]"
                            title={item.session_key}
                          >
                            {item.session_key.slice(0, 12)}...
                          </button>
                        ) : (
                          <span className="text-xs text-muted-foreground">-</span>
                        )}
                      </td>
                      <td className="px-4 py-3 max-w-xs">
                        <div className="text-xs text-slate-700 truncate max-h-16 overflow-hidden" title={item.message_content}>
                          {item.message_content || "-"}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="inline-block text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 font-medium whitespace-nowrap">
                          {ISSUE_TYPE_LABELS[item.issue_type] || item.issue_type}
                        </span>
                      </td>
                      <td className="px-4 py-3 max-w-[200px]">
                        <div className="text-xs text-slate-600 truncate" title={item.description}>
                          {item.description || "-"}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground whitespace-nowrap">
                        {new Date(item.created_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => handleDelete(globalIndex)}
                          className="text-xs text-red-500 hover:text-red-700"
                        >
                          删除
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>共 {filtered.length} 条{hasFilters ? `（筛选自 ${items.length} 条）` : ""}</span>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                className="h-7 px-2 text-xs"
                disabled={safePage <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                上一页
              </Button>
              <span>{safePage} / {totalPages}</span>
              <Button
                size="sm"
                variant="outline"
                className="h-7 px-2 text-xs"
                disabled={safePage >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              >
                下一页
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
