import React, { useState, useEffect } from "react";
import {
  ShieldCheck,
  Clock,
  Mail,
  Sparkles,
  AlertTriangle,
  X,
  CheckCircle2,
  Loader2,
} from "lucide-react";
import { api, formatCurrency, MAILPIT_WEB_URL } from "../api/client";

export default function OtpModal({
  pendingTx,
  onClose,
  onSuccess,
  onCompensatedOrFailed,
}) {
  const [otpCode, setOtpCode] = useState("");
  const [secondsLeft, setSecondsLeft] = useState(
    pendingTx?.otp_info?.expires_in_seconds || 300
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isLoadingDemoOtp, setIsLoadingDemoOtp] = useState(false);
  const [errorBox, setErrorBox] = useState(null);

  useEffect(() => {
    if (!pendingTx?.otp_info?.expires_at) return;
    const targetTime = new Date(pendingTx.otp_info.expires_at).getTime();

    const interval = setInterval(() => {
      const now = Date.now();
      const diff = Math.max(0, Math.floor((targetTime - now) / 1000));
      setSecondsLeft(diff);
    }, 1000);

    return () => clearInterval(interval);
  }, [pendingTx]);

  const formatCountdown = (sec) => {
    const mins = String(Math.floor(sec / 60)).padStart(2, "0");
    const secs = String(sec % 60).padStart(2, "0");
    return `${mins}:${secs}`;
  };

  const handleFetchDemoOtp = async () => {
    setErrorBox(null);
    setIsLoadingDemoOtp(true);
    try {
      const data = await api.getDemoOtp(pendingTx.transaction_id);
      if (data?.otp_code) {
        setOtpCode(data.otp_code);
      }
    } catch (err) {
      setErrorBox({
        code: err.code || "OTP_FETCH_ERROR",
        message: err.message,
      });
    } finally {
      setIsLoadingDemoOtp(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (otpCode.trim().length !== 6) {
      setErrorBox({
        code: "VALIDATION_ERROR",
        message: "Vui lòng nhập đầy đủ mã OTP gồm 6 chữ số.",
      });
      return;
    }

    setErrorBox(null);
    setIsSubmitting(true);
    try {
      const result = await api.confirmOtp(
        pendingTx.transaction_id,
        otpCode.trim()
      );
      onSuccess(result);
    } catch (err) {
      setErrorBox({
        code: err.code || "CONFIRM_ERROR",
        message: err.message,
        details: err.details,
        correlationId: err.correlationId,
      });
      if (
        err.code === "TUITION_ALREADY_PAID_COMPENSATED" ||
        err.code === "INSUFFICIENT_BALANCE" ||
        err.code === "OTP_EXPIRED"
      ) {
        onCompensatedOrFailed && onCompensatedOrFailed(err);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!pendingTx) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 backdrop-blur-sm p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full overflow-hidden border border-slate-200 animate-in fade-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="bg-gradient-to-r from-blue-900 to-indigo-800 px-6 py-4 text-white flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <ShieldCheck className="w-6 h-6 text-amber-300" />
            <div>
              <h3 className="font-bold text-lg">
                Xác thực Giao dịch bằng Mã OTP
              </h3>
              <p className="text-xs text-blue-200">
                Mã giao dịch: {pendingTx.transaction_code}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-blue-200 hover:text-white p-1 rounded-lg hover:bg-white/10 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <form onSubmit={handleSubmit} className="p-6 space-y-5">
          {/* Email & Countdown banner */}
          <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 flex items-center justify-between gap-4">
            <div className="text-xs text-slate-700 space-y-1">
              <p>
                Mã OTP gồm 6 chữ số đã được gửi tới email người nộp tiền:
              </p>
              <p className="font-bold text-blue-900 text-sm">
                {pendingTx.otp_info?.sent_to_email}
              </p>
              <p className="text-[11px] text-slate-500">
                • Gắn chặt với giao dịch • Không trùng OTP active khác • Chỉ dùng
                01 lần
              </p>
            </div>
            <div
              className={`flex flex-col items-center justify-center px-3.5 py-2 rounded-xl border font-mono ${
                secondsLeft > 60
                  ? "bg-white border-blue-300 text-blue-800"
                  : "bg-rose-50 border-rose-300 text-rose-700 animate-pulse"
              }`}
            >
              <div className="flex items-center gap-1 text-[11px] font-sans font-semibold uppercase">
                <Clock className="w-3.5 h-3.5" />
                <span>Hiệu lực</span>
              </div>
              <span className="text-xl font-extrabold">
                {formatCountdown(secondsLeft)}
              </span>
            </div>
          </div>

          {/* Transaction Quick Summary */}
          <div className="bg-slate-50 rounded-xl p-3.5 border border-slate-200 text-xs space-y-2">
            <div className="flex justify-between">
              <span className="text-slate-500">Sinh viên thụ hưởng:</span>
              <span className="font-bold text-slate-800">
                {pendingTx.tuition?.student_full_name} (
                {pendingTx.tuition?.student_id})
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Số tiền thanh toán (100%):</span>
              <span className="font-extrabold text-blue-700 text-sm">
                {formatCurrency(pendingTx.tuition?.amount)}
              </span>
            </div>
          </div>

          {/* OTP Input */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="block text-sm font-bold text-slate-800">
                Nhập mã xác thực OTP (6 chữ số)
              </label>
              <div className="flex items-center gap-2">
                <a
                  href={MAILPIT_WEB_URL}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs font-semibold text-blue-700 hover:underline"
                >
                  <Mail className="w-3.5 h-3.5" />
                  <span>Mở Mailpit (:8025)</span>
                </a>
                <span className="text-slate-300">|</span>
                <button
                  type="button"
                  onClick={handleFetchDemoOtp}
                  disabled={isLoadingDemoOtp || secondsLeft === 0}
                  className="inline-flex items-center gap-1 text-xs font-semibold text-amber-700 bg-amber-50 hover:bg-amber-100 border border-amber-300 px-2 py-0.5 rounded-md transition"
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  <span>
                    {isLoadingDemoOtp ? "Đang lấy..." : "Điền nhanh OTP (Demo)"}
                  </span>
                </button>
              </div>
            </div>

            <input
              type="text"
              maxLength={6}
              value={otpCode}
              onChange={(e) =>
                setOtpCode(e.target.value.replace(/[^0-9]/g, ""))
              }
              placeholder="••••••"
              disabled={secondsLeft === 0 || isSubmitting}
              className="w-full text-center text-3xl font-extrabold tracking-[0.6em] py-3.5 px-4 rounded-xl border-2 border-slate-300 focus:border-blue-600 focus:ring-4 focus:ring-blue-100 outline-none transition font-mono text-blue-900"
              autoFocus
            />
          </div>

          {/* Error Box */}
          {errorBox && (
            <div className="bg-rose-50 border border-rose-300 rounded-xl p-3.5 text-xs text-rose-800 space-y-1.5">
              <div className="flex items-center gap-2 font-bold text-rose-900">
                <AlertTriangle className="w-4 h-4 text-rose-600 shrink-0" />
                <span>[{errorBox.code}] {errorBox.message}</span>
              </div>
              {errorBox.details?.restored_balance !== undefined && (
                <p className="text-emerald-800 bg-emerald-50 border border-emerald-200 rounded-lg px-2.5 py-1.5 font-semibold">
                  ✓ Saga Compensation: Số dư của bạn đã được hoàn trả nguyên vẹn (
                  {formatCurrency(errorBox.details.restored_balance)}).
                </p>
              )}
              {errorBox.correlationId && (
                <p className="text-[11px] text-rose-600 font-mono">
                  Correlation-ID: {errorBox.correlationId}
                </p>
              )}
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2.5 rounded-xl border border-slate-300 text-slate-700 font-semibold text-sm hover:bg-slate-100 transition"
            >
              Đóng
            </button>
            <button
              type="submit"
              disabled={
                otpCode.length !== 6 || secondsLeft === 0 || isSubmitting
              }
              className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-blue-700 hover:bg-blue-800 disabled:bg-slate-300 disabled:cursor-not-allowed text-white font-bold text-sm shadow-md transition"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Đang xác thực & Thực thi Saga...</span>
                </>
              ) : (
                <>
                  <CheckCircle2 className="w-4 h-4" />
                  <span>Xác nhận OTP & Thanh toán</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
