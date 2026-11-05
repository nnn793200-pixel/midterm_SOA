import React from "react";
import {
  GitBranch,
  CheckCircle2,
  XCircle,
  RotateCcw,
  X,
  Server,
} from "lucide-react";
import { formatCurrency, formatDateTime } from "../api/client";

export default function SagaDetailModal({ detail, onClose }) {
  if (!detail) return null;

  const getStepBadge = (stepStatus) => {
    if (stepStatus === "SUCCESS") {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold bg-emerald-100 text-emerald-800">
          <CheckCircle2 className="w-3 h-3" />
          SUCCESS
        </span>
      );
    }
    if (stepStatus === "COMPENSATED") {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold bg-amber-100 text-amber-800">
          <RotateCcw className="w-3 h-3" />
          COMPENSATED (HOÀN TIỀN)
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold bg-rose-100 text-rose-800">
        <XCircle className="w-3 h-3" />
        {stepStatus}
      </span>
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 backdrop-blur-sm p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full max-h-[90vh] flex flex-col overflow-hidden border border-slate-200">
        {/* Header */}
        <div className="bg-gradient-to-r from-slate-900 to-blue-900 px-6 py-4 text-white flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <GitBranch className="w-5 h-5 text-amber-300" />
            <div>
              <h3 className="font-bold text-base">
                Chi tiết Luồng Điều phối Saga & Tracing
              </h3>
              <p className="text-xs text-slate-300 font-mono">
                {detail.transaction_code} | Correlation-ID: {detail.correlation_id}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-300 hover:text-white p-1 rounded-lg hover:bg-white/10 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 overflow-y-auto space-y-5">
          {/* Summary */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-slate-50 p-3.5 rounded-xl border border-slate-200 text-xs">
            <div>
              <p className="text-slate-500">Sinh viên (MSSV)</p>
              <p className="font-bold text-slate-800 mt-0.5">
                {detail.student_full_name} ({detail.student_id})
              </p>
            </div>
            <div>
              <p className="text-slate-500">Số tiền</p>
              <p className="font-bold text-blue-700 mt-0.5">
                {formatCurrency(detail.amount)}
              </p>
            </div>
            <div>
              <p className="text-slate-500">Trạng thái GD</p>
              <p className="font-extrabold text-slate-900 mt-0.5">
                {detail.status}
              </p>
            </div>
            <div>
              <p className="text-slate-500">Số dư Trước → Sau</p>
              <p className="font-semibold text-slate-800 mt-0.5">
                {detail.balance_before !== null
                  ? `${formatCurrency(detail.balance_before)} → ${formatCurrency(detail.balance_after)}`
                  : "Chưa trừ tiền"}
              </p>
            </div>
          </div>

          {detail.failure_reason && (
            <div className="bg-amber-50 border border-amber-300 rounded-xl p-3 text-xs text-amber-900 font-medium">
              <strong>Ghi chú trạng thái / Lý do:</strong> {detail.failure_reason}
            </div>
          )}

          {/* Saga Step Timeline */}
          <div className="space-y-3">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500">
              Nhật ký từng bước điều phối Saga (saga_step_logs)
            </h4>

            <div className="space-y-2.5">
              {(detail.saga_steps || []).map((step) => (
                <div
                  key={step.id}
                  className="border border-slate-200 rounded-xl p-3.5 bg-white shadow-sm space-y-1.5 text-xs"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="w-6 h-6 rounded-full bg-blue-100 text-blue-800 font-bold flex items-center justify-center text-[11px]">
                        #{step.step_order}
                      </span>
                      <span className="font-bold text-slate-900">
                        {step.step_name}
                      </span>
                      <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-slate-100 text-slate-600 font-mono">
                        <Server className="w-3 h-3" />
                        {step.target_service}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      {getStepBadge(step.step_status)}
                      <span className="text-[11px] text-slate-400">
                        {formatDateTime(step.created_at)}
                      </span>
                    </div>
                  </div>

                  {step.error_message && (
                    <p className="text-rose-700 bg-rose-50 px-2.5 py-1.5 rounded-lg font-medium">
                      {step.error_message}
                    </p>
                  )}

                  {step.detail_payload && (
                    <pre className="bg-slate-900 text-slate-100 p-2.5 rounded-lg text-[11px] overflow-x-auto font-mono">
                      {JSON.stringify(step.detail_payload, null, 2)}
                    </pre>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-3 bg-slate-50 border-t border-slate-200 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-slate-800 text-white text-xs font-bold hover:bg-slate-900 transition"
          >
            Đóng cửa sổ
          </button>
        </div>
      </div>
    </div>
  );
}
