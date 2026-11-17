import React, { useEffect, useRef, useState } from "react";
import { Clock, Loader2, CheckCircle2, X } from "lucide-react";
import { api } from "../api/client";

const POLL_INTERVAL_MS = 2000;

export default function WaitingModal({
  waitingInfo,
  retryInitiate,
  onGotOtp,
  onPaidDetected,
  onError,
  onCancel,
  onFinished,
}) {
  const [paidInfo, setPaidInfo] = useState(null);
  const [waitedSeconds, setWaitedSeconds] = useState(0);
  const callbacks = useRef({});
  callbacks.current = { retryInitiate, onGotOtp, onPaidDetected, onError };

  useEffect(() => {
    let stopped = false;
    let busy = false;

    const tick = async () => {
      if (busy || stopped) return;
      busy = true;
      try {
        const status = await api.getTuitionPaymentStatus(waitingInfo.student_id);
        if (stopped) return;

        if (status.state === "PAID") {
          stopped = true;
          setPaidInfo(status);
          callbacks.current.onPaidDetected?.();
          return;
        }

        if (status.state === "AVAILABLE") {
          // Người giữ chỗ trước đã thoát/hết hạn -> tự khởi tạo giao dịch cho mình và nhận OTP
          const res = await callbacks.current.retryInitiate();
          if (stopped) return;
          if (res?.status !== "WAITING_FOR_OTHER_PAYMENT") {
            stopped = true;
            callbacks.current.onGotOtp(res);
          }
        }
      } catch (err) {
        if (!stopped && err?.status && err.status !== 401) {
          // Lỗi nghiệp vụ khi khởi tạo lại (ví dụ học phí đã đóng, số dư không đủ)
          if (err.code && err.code !== "NOTIFICATION_SERVICE_UNAVAILABLE") {
            stopped = true;
            callbacks.current.onError(err);
          }
        }
      } finally {
        busy = false;
      }
    };

    const pollTimer = setInterval(tick, POLL_INTERVAL_MS);
    const clockTimer = setInterval(() => setWaitedSeconds((s) => s + 1), 1000);
    tick();

    return () => {
      stopped = true;
      clearInterval(pollTimer);
      clearInterval(clockTimer);
    };
  }, [waitingInfo.student_id]);

  const studentName = paidInfo?.student_full_name || waitingInfo.student_full_name;
  const studentId = paidInfo?.student_id || waitingInfo.student_id;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 backdrop-blur-sm p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full overflow-hidden border border-slate-200">
        <div
          className={`px-6 py-4 text-white flex items-center justify-between ${
            paidInfo
              ? "bg-gradient-to-r from-emerald-700 to-teal-600"
              : "bg-gradient-to-r from-blue-900 to-indigo-800"
          }`}
        >
          <div className="flex items-center gap-2.5">
            {paidInfo ? (
              <CheckCircle2 className="w-6 h-6" />
            ) : (
              <Clock className="w-6 h-6 text-amber-300" />
            )}
            <h3 className="font-bold text-lg">
              {paidInfo ? "Học phí đã được thanh toán" : "Đang chờ giao dịch khác"}
            </h3>
          </div>
          <button
            type="button"
            onClick={paidInfo ? onFinished : onCancel}
            className="text-blue-100 hover:text-white p-1 rounded-lg hover:bg-white/10 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-5">
          {paidInfo ? (
            <>
              <p className="text-sm text-slate-800 leading-relaxed">
                Khoản học phí của sinh viên <strong>{studentName}</strong> (
                {studentId}) đã được thanh toán thành công bởi người dùng khác.
              </p>
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={onFinished}
                  className="px-5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-sm shadow-md transition"
                >
                  Đóng
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="flex items-start gap-3">
                <Loader2 className="w-6 h-6 text-blue-700 animate-spin shrink-0 mt-0.5" />
                <div className="space-y-1.5">
                  <p className="text-sm font-semibold text-slate-900">
                    Đang có người dùng khác thực hiện thanh toán cho MSSV này.
                    Vui lòng chờ...
                  </p>
                  <p className="text-xs text-slate-600">
                    Sinh viên: <strong>{studentName}</strong> ({studentId})
                  </p>
                  <p className="text-xs text-slate-500">
                    Hệ thống tự động kiểm tra lại mỗi 2 giây • Đã chờ{" "}
                    {waitedSeconds}s
                  </p>
                </div>
              </div>
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={onCancel}
                  className="px-4 py-2.5 rounded-xl border border-slate-300 text-slate-700 font-semibold text-sm hover:bg-slate-100 transition"
                >
                  Hủy chờ
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
