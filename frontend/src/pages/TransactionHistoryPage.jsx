import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  History,
  GitBranch,
  RefreshCw,
  CheckCircle2,
  XCircle,
  RotateCcw,
  Clock,
  BookOpen,
  CreditCard,
} from "lucide-react";
import { api, formatCurrency, formatDateTime } from "../api/client";
import SagaDetailModal from "../components/SagaDetailModal";
import OtpModal from "../components/OtpModal";
import ReceiptModal from "../components/ReceiptModal";

const PENDING_WINDOW_SECONDS = 180;

const isPendingStatus = (status) =>
  status === "PENDING" || status === "PENDING_OTP";

const getPendingRemainingSeconds = (tx, nowMs) => {
  if (!tx?.created_at) return 0;
  const deadlineMs =
    new Date(tx.created_at).getTime() + PENDING_WINDOW_SECONDS * 1000;
  return Math.max(0, Math.floor((deadlineMs - nowMs) / 1000));
};

const formatCountdown = (sec) => {
  const mins = String(Math.floor(sec / 60)).padStart(2, "0");
  const secs = String(sec % 60).padStart(2, "0");
  return `${mins}:${secs}`;
};

export default function TransactionHistoryPage({
  user,
  onRefreshUser,
  refreshTrigger,
}) {
  const [transactions, setTransactions] = useState([]);
  const [ledgerEntries, setLedgerEntries] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedDetail, setSelectedDetail] = useState(null);
  const [resumingTx, setResumingTx] = useState(null);
  const [completedReceipt, setCompletedReceipt] = useState(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const expiredTriggeredRef = useRef(new Set());

  const loadData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [historyRes, accountRes] = await Promise.all([
        api.getPaymentHistory(),
        api.getMyAccount(),
      ]);
      const items = historyRes?.items || [];
      setTransactions(items);
      setLedgerEntries(accountRes?.recent_ledger_entries || []);
      setNowMs(Date.now());
      const activeIds = new Set(
        items.filter((t) => isPendingStatus(t.status)).map((t) => t.id)
      );
      for (const id of expiredTriggeredRef.current) {
        if (!activeIds.has(id)) {
          expiredTriggeredRef.current.delete(id);
        }
      }
    } catch {
      // Ignore
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData, refreshTrigger]);

  const hasPendingTransactions = transactions.some((tx) =>
    isPendingStatus(tx.status)
  );

  useEffect(() => {
    if (!hasPendingTransactions) return;
    const interval = setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => clearInterval(interval);
  }, [hasPendingTransactions]);

  // Khi bộ đếm ngược 3 phút chạm 00:00 -> tự làm mới để chuyển sang FAILED ngay không cần F5
  useEffect(() => {
    const newlyExpired = transactions.filter(
      (tx) =>
        isPendingStatus(tx.status) &&
        getPendingRemainingSeconds(tx, nowMs) === 0 &&
        !expiredTriggeredRef.current.has(tx.id)
    );
    if (newlyExpired.length === 0) return;

    newlyExpired.forEach((tx) => expiredTriggeredRef.current.add(tx.id));
    const timer = setTimeout(() => {
      loadData();
    }, 450);
    return () => clearTimeout(timer);
  }, [transactions, nowMs, loadData]);

  const handleOpenSagaDetail = async (txId) => {
    try {
      const detail = await api.getTransactionDetail(txId);
      setSelectedDetail(detail);
    } catch {
      // Ignore
    }
  };

  const handleResumePayment = (tx) => {
    const remainingSec = getPendingRemainingSeconds(tx, Date.now());
    if (remainingSec <= 0) {
      loadData();
      return;
    }
    const deadlineIso = new Date(
      new Date(tx.created_at).getTime() + PENDING_WINDOW_SECONDS * 1000
    ).toISOString();

    setResumingTx({
      transaction_id: tx.id,
      transaction_code: tx.transaction_code,
      status: tx.status,
      tuition: {
        student_id: tx.student_id,
        student_full_name: tx.student_full_name,
        semester_code: tx.semester_code,
        semester_name: tx.semester_name,
        amount: tx.amount,
      },
      otp_info: {
        sent_to_email: tx.payer_email,
        expires_in_seconds: remainingSec,
        expires_at: deadlineIso,
      },
    });
  };

  const renderStatusBadge = (tx) => {
    if (isPendingStatus(tx.status)) {
      const remaining = getPendingRemainingSeconds(tx, nowMs);
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-amber-100 text-amber-800 border border-amber-300">
          <Clock className="w-3.5 h-3.5" />
          <span>PENDING (Đang chờ xác thực)</span>
          <span className="font-mono bg-amber-200/80 text-amber-950 px-1.5 py-0.5 rounded">
            {formatCountdown(remaining)}
          </span>
        </span>
      );
    }

    switch (tx.status) {
      case "COMPLETED":
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-300">
            <CheckCircle2 className="w-3.5 h-3.5" />
            COMPLETED (Thành công)
          </span>
        );
      case "COMPENSATED":
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-bold bg-sky-100 text-sky-800 border border-sky-300">
            <RotateCcw className="w-3.5 h-3.5" />
            COMPENSATED (Đã hoàn tiền)
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-bold bg-rose-100 text-rose-800 border border-rose-300">
            <XCircle className="w-3.5 h-3.5" />
            {tx.status}
          </span>
        );
    }
  };

  return (
    <div className="space-y-6">
      {/* Section 1: Payment Transactions */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
        <div className="bg-slate-900 text-white px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <History className="w-5 h-5 text-amber-300" />
            <div>
              <h2 className="font-bold text-sm uppercase tracking-wider">
                Lịch sử Giao dịch Đóng học phí ({transactions.length})
              </h2>
              <p className="text-xs text-slate-300">
                Tài khoản: {user?.full_name} ({user?.username})
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={loadData}
            disabled={isLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-white/10 hover:bg-white/20 text-xs font-semibold transition"
          >
            <RefreshCw
              className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`}
            />
            <span>Làm mới</span>
          </button>
        </div>

        <div className="overflow-x-auto">
          {transactions.length === 0 ? (
            <div className="p-10 text-center text-sm text-slate-500">
              Chưa có giao dịch nào được thực hiện trên tài khoản này.
            </div>
          ) : (
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-slate-100 text-slate-600 uppercase font-bold border-b border-slate-200">
                  <th className="py-3.5 px-4">Mã Giao dịch</th>
                  <th className="py-3.5 px-4">Sinh viên (MSSV)</th>
                  <th className="py-3.5 px-4">Học kỳ</th>
                  <th className="py-3.5 px-4 text-right">Số tiền</th>
                  <th className="py-3.5 px-4 text-right">Số dư Sau GD</th>
                  <th className="py-3.5 px-4">Trạng thái</th>
                  <th className="py-3.5 px-4">Thời gian</th>
                  <th className="py-3.5 px-4 text-center">Chi tiết</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {transactions.map((tx) => {
                  const canResume =
                    isPendingStatus(tx.status) &&
                    getPendingRemainingSeconds(tx, nowMs) > 0;
                  return (
                    <tr
                      key={tx.id}
                      onClick={
                        canResume ? () => handleResumePayment(tx) : undefined
                      }
                      className={`transition-colors ${
                        canResume
                          ? "bg-amber-50/40 hover:bg-amber-50 cursor-pointer"
                          : "hover:bg-slate-50"
                      }`}
                    >
                      <td className="py-3.5 px-4 font-mono font-bold text-blue-800">
                        {tx.transaction_code}
                      </td>
                      <td className="py-3.5 px-4">
                        <div className="font-bold text-slate-900">
                          {tx.student_full_name}
                        </div>
                        <div className="text-slate-500 font-mono">
                          MSSV: {tx.student_id}
                        </div>
                      </td>
                      <td className="py-3.5 px-4 text-slate-700">
                        {tx.semester_name}
                      </td>
                      <td className="py-3.5 px-4 text-right font-extrabold text-slate-900">
                        {formatCurrency(tx.amount)}
                      </td>
                      <td className="py-3.5 px-4 text-right font-semibold text-blue-800">
                        {tx.balance_after !== null
                          ? formatCurrency(tx.balance_after)
                          : "—"}
                      </td>
                      <td className="py-3.5 px-4">
                        {renderStatusBadge(tx)}
                        {tx.failure_reason && (
                          <p className="text-[11px] text-slate-500 mt-1 max-w-xs">
                            {tx.failure_reason}
                          </p>
                        )}
                      </td>
                      <td className="py-3.5 px-4 text-slate-600">
                        {formatDateTime(tx.completed_at || tx.created_at)}
                      </td>
                      <td className="py-3.5 px-4 text-center">
                        <div className="inline-flex items-center justify-center gap-2">
                          {canResume && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleResumePayment(tx);
                              }}
                              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-600 text-white font-bold text-xs shadow-sm transition"
                            >
                              <CreditCard className="w-3.5 h-3.5" />
                              <span>Thanh toán tiếp</span>
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleOpenSagaDetail(tx.id);
                            }}
                            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-blue-50 hover:bg-blue-100 text-blue-800 border border-blue-200 font-bold text-xs transition"
                          >
                            <GitBranch className="w-3.5 h-3.5" />
                            <span>Xem chi tiết</span>
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Section 2: Account Balance Ledger (Sổ cái biến động số dư) */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
        <div className="bg-blue-950 text-white px-6 py-3.5 flex items-center gap-2.5">
          <BookOpen className="w-4 h-4 text-emerald-300" />
          <h3 className="font-bold text-xs uppercase tracking-wider">
            Sổ cái Biến động Số dư Tài khoản
          </h3>
        </div>

        <div className="overflow-x-auto">
          {ledgerEntries.length === 0 ? (
            <div className="p-8 text-center text-xs text-slate-500">
              Chưa có bút toán biến động số dư nào.
            </div>
          ) : (
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-slate-100 text-slate-600 uppercase font-bold border-b border-slate-200">
                  <th className="py-3 px-4">Loại Bút toán</th>
                  <th className="py-3 px-4 text-right">Số dư Trước</th>
                  <th className="py-3 px-4 text-right">Số tiền Biến động</th>
                  <th className="py-3 px-4 text-right">Số dư Sau</th>
                  <th className="py-3 px-4">Nội dung Đối soát</th>
                  <th className="py-3 px-4">Thời gian</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {ledgerEntries.map((entry) => {
                  const isDebit = entry.entry_type === "DEBIT";
                  return (
                    <tr key={entry.id} className="hover:bg-slate-50">
                      <td className="py-3 px-4">
                        <span
                          className={`px-2 py-0.5 rounded-full text-[11px] font-bold ${
                            isDebit
                              ? "bg-rose-100 text-rose-800"
                              : "bg-emerald-100 text-emerald-800"
                          }`}
                        >
                          {isDebit
                            ? "DEBIT (Trừ tiền)"
                            : "COMPENSATION_REFUND (Hoàn tiền)"}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-right font-medium text-slate-700">
                        {formatCurrency(entry.balance_before)}
                      </td>
                      <td
                        className={`py-3 px-4 text-right font-extrabold ${
                          isDebit ? "text-rose-700" : "text-emerald-700"
                        }`}
                      >
                        {isDebit ? "-" : "+"}
                        {formatCurrency(entry.amount)}
                      </td>
                      <td className="py-3 px-4 text-right font-extrabold text-blue-900">
                        {formatCurrency(entry.balance_after)}
                      </td>
                      <td className="py-3 px-4 text-slate-700">
                        {entry.description}
                      </td>
                      <td className="py-3 px-4 text-slate-500">
                        {formatDateTime(entry.created_at)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Chi tiết xử lý giao dịch */}
      {selectedDetail && (
        <SagaDetailModal
          detail={selectedDetail}
          onClose={() => setSelectedDetail(null)}
        />
      )}

      {/* Tiếp tục nhập OTP từ Lịch sử giao dịch */}
      {resumingTx && (
        <OtpModal
          pendingTx={resumingTx}
          onClose={() => setResumingTx(null)}
          onSuccess={async (receiptData) => {
            setResumingTx(null);
            setCompletedReceipt(receiptData);
            onRefreshUser && (await onRefreshUser());
            await loadData();
          }}
          onCompensatedOrFailed={async () => {
            onRefreshUser && (await onRefreshUser());
            await loadData();
          }}
          onExpired={loadData}
        />
      )}

      {/* Biên lai sau khi thanh toán tiếp thành công */}
      {completedReceipt && (
        <ReceiptModal
          receipt={completedReceipt}
          onClose={() => setCompletedReceipt(null)}
          onViewHistory={() => {
            setCompletedReceipt(null);
            loadData();
          }}
        />
      )}
    </div>
  );
}
