import React from "react";
import {
  CheckCircle2,
  AlertTriangle,
  Mail,
  History,
  FileText,
  X,
} from "lucide-react";
import {
  formatCurrency,
  formatDateTime,
  MAILPIT_WEB_URL,
} from "../api/client";

export default function ReceiptModal({
  receipt,
  onClose,
  onViewHistory,
}) {
  if (!receipt) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 backdrop-blur-sm p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full overflow-hidden border border-slate-200 animate-in fade-in zoom-in-95 duration-200">
        {/* Top Green Header */}
        <div className="bg-gradient-to-r from-emerald-700 to-teal-600 px-6 py-5 text-white flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-full bg-white/20 flex items-center justify-center">
              <CheckCircle2 className="w-7 h-7 text-white" />
            </div>
            <div>
              <h3 className="font-extrabold text-lg">
                Thanh toán Học phí Thành công!
              </h3>
              <p className="text-xs text-emerald-100">
                Mã giao dịch: {receipt.transaction_code}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-emerald-100 hover:text-white p-1 rounded-lg hover:bg-white/10 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Receipt Details */}
        <div className="p-6 space-y-4">
          <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-3.5 text-center">
            <p className="text-xs font-semibold text-emerald-700 uppercase">
              Số tiền đã thanh toán (100% học phí)
            </p>
            <p className="text-2xl font-extrabold text-emerald-800 mt-0.5">
              {formatCurrency(receipt.tuition?.amount)}
            </p>
          </div>

          <div className="bg-slate-50 rounded-xl border border-slate-200 p-4 text-xs space-y-2.5">
            <div className="flex justify-between border-b border-slate-200 pb-2">
              <span className="text-slate-500">Người nộp tiền:</span>
              <span className="font-bold text-slate-800">
                {receipt.payer?.full_name} ({receipt.payer?.phone_number})
              </span>
            </div>
            <div className="flex justify-between border-b border-slate-200 pb-2">
              <span className="text-slate-500">Email nhận biên lai:</span>
              <span className="font-semibold text-blue-700">
                {receipt.payer?.email}
              </span>
            </div>
            <div className="flex justify-between border-b border-slate-200 pb-2">
              <span className="text-slate-500">Sinh viên thụ hưởng (MSSV):</span>
              <span className="font-bold text-slate-800">
                {receipt.tuition?.student_full_name} (
                {receipt.tuition?.student_id})
              </span>
            </div>
            <div className="flex justify-between border-b border-slate-200 pb-2">
              <span className="text-slate-500">Học kỳ:</span>
              <span className="font-medium text-slate-800">
                {receipt.tuition?.semester_name}
              </span>
            </div>
            <div className="flex justify-between border-b border-slate-200 pb-2">
              <span className="text-slate-500">Trạng thái khoản học phí:</span>
              <span className="px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 font-bold text-[11px]">
                ĐÃ THANH TOÁN ({receipt.tuition?.tuition_status || "PAID"})
              </span>
            </div>
            <div className="flex justify-between border-b border-slate-200 pb-2">
              <span className="text-slate-500">Số dư trước giao dịch:</span>
              <span className="font-medium text-slate-700">
                {formatCurrency(receipt.payer?.balance_before)}
              </span>
            </div>
            <div className="flex justify-between border-b border-slate-200 pb-2">
              <span className="text-slate-500">Số dư khả dụng còn lại:</span>
              <span className="font-extrabold text-blue-800">
                {formatCurrency(receipt.payer?.balance_after)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Thời gian hoàn tất:</span>
              <span className="font-medium text-slate-700">
                {formatDateTime(receipt.completed_at)}
              </span>
            </div>
          </div>

          {receipt.receipt_email_sent !== false ? (
            <div className="bg-blue-50 border border-blue-200 rounded-xl p-3 flex items-center justify-between text-xs text-blue-900">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-blue-700 shrink-0" />
                <span>
                  Email xác nhận giao dịch thành công đã được gửi qua SMTP.
                </span>
              </div>
              <a
                href={MAILPIT_WEB_URL}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 font-bold text-blue-700 hover:underline shrink-0 ml-2"
              >
                <Mail className="w-3.5 h-3.5" />
                <span>Xem Email</span>
              </a>
            </div>
          ) : (
            <div className="bg-amber-50 border border-amber-300 rounded-xl p-3 flex items-center justify-between gap-2 text-xs text-amber-900">
              <div className="flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                <div className="space-y-0.5">
                  <p className="font-bold">
                    Giao dịch đã thanh toán thành công nhưng gửi email biên lai
                    gặp sự cố.
                  </p>
                  {receipt.message && (
                    <p className="text-[11px] text-amber-800">
                      {receipt.message}
                    </p>
                  )}
                </div>
              </div>
              <a
                href={MAILPIT_WEB_URL}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 font-bold text-amber-800 hover:underline shrink-0 ml-2"
              >
                <Mail className="w-3.5 h-3.5" />
                <span>Xem Email</span>
              </a>
            </div>
          )}

          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onViewHistory}
              className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl border border-slate-300 text-slate-700 font-semibold text-sm hover:bg-slate-100 transition"
            >
              <History className="w-4 h-4" />
              <span>Xem Lịch sử Giao dịch</span>
            </button>
            <button
              type="button"
              onClick={onClose}
              className="px-5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-sm shadow-md transition"
            >
              Hoàn tất
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
