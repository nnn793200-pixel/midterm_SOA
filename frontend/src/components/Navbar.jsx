import React from "react";
import {
  Landmark,
  CreditCard,
  History,
  Mail,
  RotateCcw,
  LogOut,
  Wallet,
  UserCheck,
} from "lucide-react";
import { formatCurrency, MAILPIT_WEB_URL } from "../api/client";

export default function Navbar({
  user,
  activeTab,
  setActiveTab,
  onLogout,
  onResetDemo,
  isResetting,
}) {
  return (
    <header className="bg-gradient-to-r from-blue-900 via-blue-800 to-indigo-900 text-white shadow-lg sticky top-0 z-30">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex flex-wrap items-center justify-between py-3 gap-4">
          {/* Brand */}
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-xl bg-white/15 backdrop-blur flex items-center justify-center border border-white/25 shadow-inner">
              <Landmark className="w-6 h-6 text-amber-300" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-extrabold text-lg tracking-tight">
                  TDTU iBANKING
                </span>
                <span className="text-[11px] font-semibold uppercase px-2 py-0.5 rounded-full bg-amber-400/20 text-amber-300 border border-amber-300/30">
                  SOA Microservices
                </span>
              </div>
              <p className="text-xs text-blue-200">
                Phân hệ Đóng học phí Trực tuyến – ĐH Tôn Đức Thắng
              </p>
            </div>
          </div>

          {/* Navigation Tabs */}
          <nav className="flex items-center gap-2 bg-blue-950/50 p-1.5 rounded-xl border border-white/10">
            <button
              type="button"
              onClick={() => setActiveTab("payment")}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all ${
                activeTab === "payment"
                  ? "bg-white text-blue-900 shadow-sm"
                  : "text-blue-100 hover:bg-white/10"
              }`}
            >
              <CreditCard className="w-4 h-4" />
              <span>Thanh toán Học phí</span>
            </button>

            <button
              type="button"
              onClick={() => setActiveTab("history")}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all ${
                activeTab === "history"
                  ? "bg-white text-blue-900 shadow-sm"
                  : "text-blue-100 hover:bg-white/10"
              }`}
            >
              <History className="w-4 h-4" />
              <span>Lịch sử GD & Saga Logs</span>
            </button>

            <a
              href={MAILPIT_WEB_URL}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold bg-emerald-500/20 text-emerald-200 border border-emerald-400/30 hover:bg-emerald-500/30 transition"
              title="Mở hộp thư Mailpit để xem Email OTP & Biên lai"
            >
              <Mail className="w-4 h-4 text-emerald-300" />
              <span className="hidden md:inline">Hộp thư Email (:8025)</span>
            </a>
          </nav>

          {/* User Info & Actions */}
          <div className="flex items-center gap-3">
            <div className="bg-blue-950/60 border border-white/15 rounded-xl px-3.5 py-1.5 flex items-center gap-3">
              <div className="text-right">
                <div className="flex items-center justify-end gap-1.5 text-xs font-medium text-blue-200">
                  <UserCheck className="w-3.5 h-3.5 text-emerald-400" />
                  <span>{user?.full_name}</span>
                  <span className="text-blue-300">({user?.username})</span>
                </div>
                <div className="flex items-center justify-end gap-1 text-sm font-bold text-amber-300">
                  <Wallet className="w-3.5 h-3.5" />
                  <span>{formatCurrency(user?.available_balance)}</span>
                </div>
              </div>
            </div>

            <button
              type="button"
              onClick={onResetDemo}
              disabled={isResetting}
              className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 border border-amber-400/30 transition disabled:opacity-50"
              title="Khôi phục số dư & trạng thái học phí UNPAID ban đầu để demo lại"
            >
              <RotateCcw
                className={`w-4 h-4 ${isResetting ? "animate-spin" : ""}`}
              />
              <span className="hidden xl:inline">Reset Demo</span>
            </button>

            <button
              type="button"
              onClick={onLogout}
              className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 border border-rose-400/30 transition"
              title="Đăng xuất"
            >
              <LogOut className="w-4 h-4" />
              <span className="hidden sm:inline">Thoát</span>
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
