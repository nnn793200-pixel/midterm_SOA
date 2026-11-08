import React, { useState, useEffect } from "react";
import {
  User,
  Phone,
  Mail,
  GraduationCap,
  Search,
  Wallet,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ShieldCheck,
  Sparkles,
  Lock,
  Loader2,
  Info,
} from "lucide-react";
import { api, formatCurrency, generateUuid } from "../api/client";
import OtpModal from "../components/OtpModal";
import ReceiptModal from "../components/ReceiptModal";

export default function TuitionPaymentPage({
  user,
  onRefreshUser,
  onNavigateHistory,
  refreshTrigger,
}) {
  const [mssvInput, setMssvInput] = useState("524K0032");
  const [sampleTuitions, setSampleTuitions] = useState([]);
  const [tuitionResult, setTuitionResult] = useState(null);
  const [lookupError, setLookupError] = useState(null);
  const [isLookingUp, setIsLookingUp] = useState(false);

  const [termsAccepted, setTermsAccepted] = useState(false);
  const [isInitiating, setIsInitiating] = useState(false);
  const [initiateError, setInitiateError] = useState(null);

  const [pendingTx, setPendingTx] = useState(null);
  const [completedReceipt, setCompletedReceipt] = useState(null);

  // Load danh sách MSSV mẫu để chọn nhanh khi Demo
  const fetchSampleTuitions = async () => {
    try {
      const list = await api.listAllTuitions();
      setSampleTuitions(Array.isArray(list) ? list : []);
    } catch {
      // Ignore
    }
  };

  useEffect(() => {
    fetchSampleTuitions();
  }, [refreshTrigger]);

  // Tự động tra cứu học phí khi người dùng nhập MSSV (Debounce 300ms)
  useEffect(() => {
    const trimmed = mssvInput.trim();
    if (!trimmed || trimmed.length < 4) {
      setIsLookingUp(false);
      setTuitionResult(null);
      setLookupError(null);
      return;
    }

    let cancelled = false;
    setIsLookingUp(true);
    setLookupError(null);

    const timer = setTimeout(async () => {
      try {
        const res = await api.lookupTuitionByMssv(trimmed);
        if (!cancelled) {
          setTuitionResult(res);
        }
      } catch (err) {
        if (!cancelled) {
          setTuitionResult(null);
          setLookupError(
            err.message || `Không tìm thấy thông tin học phí cho MSSV ${trimmed}`
          );
        }
      } finally {
        if (!cancelled) {
          setIsLookingUp(false);
        }
      }
    }, 300);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [mssvInput, refreshTrigger]);

  // Kiểm tra 4 điều kiện bắt buộc để mở khóa nút "Xác nhận giao dịch"
  const bill = tuitionResult?.tuition_bill;
  const student = tuitionResult?.student;

  const hasValidTuition = Boolean(bill && student);
  const isTuitionUnpaid = Boolean(bill && bill.status === "UNPAID");
  const payerBalance = Number(user?.available_balance || 0);
  const requiredAmount = Number(bill?.amount || 0);
  const hasSufficientBalance =
    hasValidTuition && payerBalance >= requiredAmount;

  const canSubmitPayment =
    hasValidTuition &&
    isTuitionUnpaid &&
    hasSufficientBalance &&
    termsAccepted &&
    !isLookingUp &&
    !isInitiating;

  const handleInitiatePayment = async (e) => {
    e.preventDefault();
    if (!canSubmitPayment) return;

    setInitiateError(null);
    setIsInitiating(true);
    try {
      const idempotencyKey = generateUuid();
      const res = await api.initiatePayment(
        {
          student_id: student.student_id,
          tuition_bill_id: bill.id,
          amount: requiredAmount,
          terms_accepted: termsAccepted,
        },
        idempotencyKey
      );
      setPendingTx(res);
    } catch (err) {
      setInitiateError({
        code: err.code || "INITIATE_FAILED",
        message: err.message,
        correlationId: err.correlationId,
      });
    } finally {
      setIsInitiating(false);
    }
  };

  const handleOtpSuccess = async (receiptData) => {
    setPendingTx(null);
    setCompletedReceipt(receiptData);
    await onRefreshUser();
    await fetchSampleTuitions();
    if (mssvInput.trim()) {
      try {
        const updated = await api.lookupTuitionByMssv(mssvInput.trim());
        setTuitionResult(updated);
      } catch {
        // Ignore
      }
    }
  };

  const handleCompensatedOrFailed = async () => {
    await onRefreshUser();
    await fetchSampleTuitions();
    if (mssvInput.trim()) {
      try {
        const updated = await api.lookupTuitionByMssv(mssvInput.trim());
        setTuitionResult(updated);
      } catch {
        // Ignore
      }
    }
  };

  return (
    <div className="space-y-6">
      {/* Quick MSSV Selector Bar for Demo */}
      <div className="bg-white rounded-2xl p-4 shadow-sm border border-slate-200 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs font-bold text-slate-700">
          <Sparkles className="w-4 h-4 text-amber-500" />
          <span>Chọn nhanh Sinh viên TDTU mẫu (Click để tra cứu MSSV):</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {sampleTuitions.map((item) => {
            const st = item.student;
            const tb = item.tuition_bill;
            const isSelected = mssvInput.trim() === st.student_id;
            const isPaid = tb.status === "PAID";
            return (
              <button
                key={st.student_id}
                type="button"
                onClick={() => {
                  setMssvInput(st.student_id);
                  setInitiateError(null);
                }}
                className={`px-3 py-1.5 rounded-xl text-xs font-semibold border transition flex items-center gap-2 ${
                  isSelected
                    ? "bg-blue-700 text-white border-blue-700 shadow-sm"
                    : "bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100"
                }`}
              >
                <span className="font-mono font-bold">{st.student_id}</span>
                <span>• {st.full_name}</span>
                <span
                  className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ${
                    isPaid
                      ? isSelected
                        ? "bg-rose-200 text-rose-900"
                        : "bg-rose-100 text-rose-700"
                      : isSelected
                      ? "bg-emerald-200 text-emerald-950"
                      : "bg-emerald-100 text-emerald-800"
                  }`}
                >
                  {isPaid ? "PAID" : formatCurrency(tb.amount)}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Main 3-Section Form */}
      <form
        onSubmit={handleInitiatePayment}
        className="grid grid-cols-1 lg:grid-cols-12 gap-6"
      >
        {/* Left Column: Section A (Payer) + Section B (Tuition Lookup) */}
        <div className="lg:col-span-7 space-y-6">
          {/* NHÓM A: NGƯỜI NỘP TIỀN (READ-ONLY) */}
          <section className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
            <div className="bg-slate-900 text-white px-6 py-3.5 flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="w-6 h-6 rounded-lg bg-blue-500 text-white font-extrabold text-xs flex items-center justify-center">
                  a
                </span>
                <h2 className="font-bold text-sm uppercase tracking-wider">
                  Thông tin Người nộp tiền
                </h2>
              </div>
              <span className="inline-flex items-center gap-1 text-[11px] bg-white/10 text-slate-200 px-2.5 py-1 rounded-full">
                <Lock className="w-3 h-3 text-amber-300" />
                Tự động lấy từ tài khoản đăng nhập (Không chỉnh sửa)
              </span>
            </div>

            <div className="p-6 grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div>
                <label className="block text-xs font-bold text-slate-500 mb-1.5">
                  Họ và tên người nộp
                </label>
                <div className="relative">
                  <User className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    value={user?.full_name || ""}
                    readOnly
                    disabled
                    className="w-full pl-9 pr-3 py-2.5 rounded-xl bg-slate-100 border border-slate-200 text-slate-700 font-bold text-sm cursor-not-allowed select-none"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-500 mb-1.5">
                  Số điện thoại
                </label>
                <div className="relative">
                  <Phone className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    value={user?.phone_number || ""}
                    readOnly
                    disabled
                    className="w-full pl-9 pr-3 py-2.5 rounded-xl bg-slate-100 border border-slate-200 text-slate-700 font-semibold text-sm cursor-not-allowed select-none"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-500 mb-1.5">
                  Địa chỉ Email (Nhận OTP & Biên lai)
                </label>
                <div className="relative">
                  <Mail className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="email"
                    value={user?.email || ""}
                    readOnly
                    disabled
                    className="w-full pl-9 pr-3 py-2.5 rounded-xl bg-slate-100 border border-slate-200 text-blue-800 font-semibold text-sm cursor-not-allowed select-none"
                  />
                </div>
              </div>
            </div>
          </section>

          {/* NHÓM B: THÔNG TIN HỌC PHÍ */}
          <section className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
            <div className="bg-blue-900 text-white px-6 py-3.5 flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="w-6 h-6 rounded-lg bg-amber-400 text-blue-950 font-extrabold text-xs flex items-center justify-center">
                  b
                </span>
                <h2 className="font-bold text-sm uppercase tracking-wider">
                  Thông tin Học phí Sinh viên TDTU
                </h2>
              </div>
              <span className="text-xs text-blue-200 flex items-center gap-1">
                <GraduationCap className="w-4 h-4" />
                Tự động tra cứu khi nhập MSSV
              </span>
            </div>

            <div className="p-6 space-y-5">
              {/* MSSV Input */}
              <div>
                <label className="block text-xs font-bold uppercase text-slate-700 mb-1.5">
                  Mã số sinh viên (MSSV) cần đóng học phí *
                </label>
                <div className="relative">
                  <Search className="w-4 h-4 text-blue-600 absolute left-3.5 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    value={mssvInput}
                    onChange={(e) => setMssvInput(e.target.value)}
                    placeholder="Nhập MSSV TDTU (VD: 524K0032, 524K0033, 524V0007...)"
                    className="w-full pl-10 pr-28 py-3 rounded-xl border-2 border-blue-300 focus:border-blue-600 focus:ring-4 focus:ring-blue-100 outline-none text-base font-bold font-mono text-slate-900 transition"
                  />
                  {isLookingUp && (
                    <span className="absolute right-3.5 top-1/2 -translate-y-1/2 inline-flex items-center gap-1 text-xs font-semibold text-blue-600">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Đang tra cứu...
                    </span>
                  )}
                </div>
              </div>

              {/* Lookup Result or Error */}
              {lookupError && (
                <div className="bg-rose-50 border border-rose-200 rounded-xl p-4 flex items-center gap-3 text-xs text-rose-800 font-medium">
                  <XCircle className="w-5 h-5 text-rose-600 shrink-0" />
                  <span>{lookupError}</span>
                </div>
              )}

              {tuitionResult && (
                <div className="bg-slate-50 rounded-2xl p-5 border border-slate-200 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-3">
                    <div>
                      <p className="text-[11px] font-bold uppercase text-slate-400">
                        Họ và tên sinh viên
                      </p>
                      <h3 className="text-lg font-extrabold text-slate-900">
                        {student.full_name}{" "}
                        <span className="text-sm font-mono text-blue-700">
                          ({student.student_id})
                        </span>
                      </h3>
                      <p className="text-xs text-slate-600">
                        {student.faculty} — Ngành: {student.major} (Lớp:{" "}
                        {student.class_code})
                      </p>
                    </div>

                    <div>
                      {bill.status === "UNPAID" ? (
                        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-extrabold bg-amber-100 text-amber-800 border border-amber-300">
                          <ClockIcon />
                          CHƯA THANH TOÁN (UNPAID)
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-extrabold bg-emerald-100 text-emerald-800 border border-emerald-300">
                          <CheckCircle2 className="w-4 h-4" />
                          ĐÃ THANH TOÁN (PAID)
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-bold text-slate-500 mb-1">
                        Kỳ học phí
                      </label>
                      <input
                        type="text"
                        value={`${bill.semester_name} (${bill.semester_code})`}
                        readOnly
                        disabled
                        className="w-full px-3.5 py-2.5 rounded-xl bg-white border border-slate-200 text-slate-800 font-semibold text-xs cursor-not-allowed"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-slate-500 mb-1">
                        Số tiền học phí cần thanh toán (100% toàn bộ)
                      </label>
                      <input
                        type="text"
                        value={formatCurrency(bill.amount)}
                        readOnly
                        disabled
                        className="w-full px-3.5 py-2.5 rounded-xl bg-blue-50 border border-blue-200 text-blue-900 font-extrabold text-sm cursor-not-allowed"
                      />
                    </div>
                  </div>

                  <div className="flex items-center gap-2 text-[11px] text-slate-600 bg-blue-50/70 px-3 py-2 rounded-lg border border-blue-100">
                    <Info className="w-4 h-4 text-blue-600 shrink-0" />
                    <span>
                      <strong>Quy định:</strong> Hệ thống chỉ cho phép{" "}
                      <strong>thanh toán toàn bộ khoản học phí</strong>, không
                      thực hiện thanh toán một phần.
                    </span>
                  </div>
                </div>
              )}
            </div>
          </section>
        </div>

        {/* Right Column: Section C (Payment Details, Conditions & Submit) */}
        <div className="lg:col-span-5 space-y-6">
          <section className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden sticky top-24">
            <div className="bg-gradient-to-r from-indigo-900 to-blue-900 text-white px-6 py-3.5 flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="w-6 h-6 rounded-lg bg-emerald-400 text-slate-950 font-extrabold text-xs flex items-center justify-center">
                  c
                </span>
                <h2 className="font-bold text-sm uppercase tracking-wider">
                  Thông tin Thanh toán & Xác nhận
                </h2>
              </div>
              <Wallet className="w-4 h-4 text-amber-300" />
            </div>

            <div className="p-6 space-y-5">
              {/* Balance & Amount Breakdown */}
              <div className="bg-slate-50 rounded-2xl p-4 border border-slate-200 space-y-3">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-600 font-medium">
                    Số dư khả dụng của người nộp:
                  </span>
                  <span className="font-extrabold text-base text-slate-900">
                    {formatCurrency(payerBalance)}
                  </span>
                </div>

                <div className="flex items-center justify-between text-xs border-t border-slate-200 pt-3">
                  <span className="text-slate-600 font-medium">
                    Số tiền cần thanh toán:
                  </span>
                  <span className="font-extrabold text-lg text-blue-700">
                    {hasValidTuition ? formatCurrency(requiredAmount) : "0 VNĐ"}
                  </span>
                </div>

                {hasValidTuition && isTuitionUnpaid && (
                  <div className="flex items-center justify-between text-xs border-t border-slate-200 pt-3">
                    <span className="text-slate-600 font-medium">
                      Số dư dự kiến sau thanh toán:
                    </span>
                    <span
                      className={`font-bold text-sm ${
                        hasSufficientBalance
                          ? "text-emerald-700"
                          : "text-rose-600"
                      }`}
                    >
                      {hasSufficientBalance
                        ? formatCurrency(payerBalance - requiredAmount)
                        : "Không đủ số dư khả dụng"}
                    </span>
                  </div>
                )}
              </div>

              {/* Validation Checklist */}
              <div className="bg-slate-50 rounded-xl p-3.5 border border-slate-200 space-y-2 text-xs">
                <p className="font-bold text-slate-700 uppercase text-[11px]">
                  Điều kiện kích hoạt giao dịch:
                </p>
                <ConditionRow
                  ok={hasValidTuition}
                  label="Khoản học phí của MSSV tồn tại trên hệ thống"
                />
                <ConditionRow
                  ok={hasValidTuition && isTuitionUnpaid}
                  label="Khoản học phí chưa được thanh toán (UNPAID)"
                />
                <ConditionRow
                  ok={hasSufficientBalance}
                  label="Số dư khả dụng >= Số tiền học phí cần thanh toán"
                />
                <ConditionRow
                  ok={termsAccepted}
                  label="Đã đồng ý với thỏa thuận và điều khoản hệ thống"
                />
              </div>

              {/* Terms & Conditions Box */}
              <div className="space-y-2.5">
                <div className="bg-slate-50 border border-slate-200 rounded-xl p-3 text-[11px] text-slate-600 leading-relaxed max-h-28 overflow-y-auto">
                  <p className="font-bold text-slate-800 mb-1">
                    THỎA THUẬN VÀ ĐIỀU KHOẢN THANH TOÁN HỌC PHÍ TDTU iBANKING:
                  </p>
                  <p>
                    1. Người nộp tiền cam kết sử dụng nguồn tiền hợp pháp từ số
                    dư khả dụng của tài khoản đang đăng nhập để thanh toán{" "}
                    <strong>toàn bộ (100%)</strong> khoản học phí cho sinh viên
                    TDTU có MSSV đã chọn.
                  </p>
                  <p className="mt-1">
                    2. Giao dịch phải được xác thực bằng mã OTP gửi qua email
                    của người nộp tiền (hiệu lực tối đa 5 phút, chỉ sử dụng 1
                    lần). Sau khi gạch nợ thành công, giao dịch không thể hủy
                    ngang.
                  </p>
                </div>

                <label className="flex items-start gap-2.5 cursor-pointer select-none p-2 rounded-xl hover:bg-blue-50/50 transition">
                  <input
                    type="checkbox"
                    checked={termsAccepted}
                    onChange={(e) => setTermsAccepted(e.target.checked)}
                    className="mt-0.5 w-4 h-4 rounded border-slate-300 text-blue-700 focus:ring-blue-600"
                  />
                  <span className="text-xs font-semibold text-slate-800">
                    Tôi đã đọc, hiểu rõ và đồng ý với các thỏa thuận và điều
                    khoản của hệ thống TDTU iBanking.
                  </span>
                </label>
              </div>

              {/* Error Alert */}
              {initiateError && (
                <div className="bg-rose-50 border border-rose-200 rounded-xl p-3 text-xs text-rose-800 space-y-1">
                  <div className="flex items-center gap-2 font-bold">
                    <AlertTriangle className="w-4 h-4 text-rose-600 shrink-0" />
                    <span>
                      [{initiateError.code}] {initiateError.message}
                    </span>
                  </div>
                </div>
              )}

              {/* Submit Button */}
              <button
                type="submit"
                disabled={!canSubmitPayment}
                className="w-full py-3.5 px-6 rounded-xl bg-blue-700 hover:bg-blue-800 disabled:bg-slate-300 disabled:text-slate-500 disabled:cursor-not-allowed text-white font-extrabold text-sm shadow-lg shadow-blue-700/20 flex items-center justify-center gap-2 transition"
              >
                {isInitiating ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Đang khởi tạo giao dịch & Gửi OTP...</span>
                  </>
                ) : (
                  <>
                    <ShieldCheck className="w-5 h-5" />
                    <span>Xác nhận giao dịch (Nhận mã OTP qua Email)</span>
                  </>
                )}
              </button>
            </div>
          </section>
        </div>
      </form>

      {/* OTP Modal */}
      {pendingTx && (
        <OtpModal
          pendingTx={pendingTx}
          onClose={() => setPendingTx(null)}
          onSuccess={handleOtpSuccess}
          onCompensatedOrFailed={handleCompensatedOrFailed}
        />
      )}

      {/* Receipt Modal */}
      {completedReceipt && (
        <ReceiptModal
          receipt={completedReceipt}
          onClose={() => setCompletedReceipt(null)}
          onViewHistory={() => {
            setCompletedReceipt(null);
            onNavigateHistory();
          }}
        />
      )}
    </div>
  );
}

function ConditionRow({ ok, label }) {
  return (
    <div className="flex items-center gap-2">
      {ok ? (
        <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
      ) : (
        <XCircle className="w-4 h-4 text-slate-300 shrink-0" />
      )}
      <span
        className={
          ok ? "text-slate-800 font-semibold" : "text-slate-400 font-normal"
        }
      >
        {label}
      </span>
    </div>
  );
}

function ClockIcon() {
  return (
    <svg
      className="w-3.5 h-3.5"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      viewBox="0 0 24 24"
    >
      <circle cx="12" cy="12" r="10" />
      <path d="M12 6v6l4 2" />
    </svg>
  );
}
