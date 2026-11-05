import React, { useState, useEffect } from "react";
import {
  Landmark,
  Lock,
  User,
  ArrowRight,
  Sparkles,
  Wallet,
  AlertCircle,
  ShieldCheck,
  Loader2,
} from "lucide-react";
import { api, formatCurrency } from "../api/client";

export default function LoginPage({ onLoginSuccess }) {
  const [username, setUsername] = useState("nguyenvana");
  const [password, setPassword] = useState("Password@123");
  const [demoUsers, setDemoUsers] = useState([]);
  const [defaultPassword, setDefaultPassword] = useState("Password@123");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  useEffect(() => {
    api
      .getDemoUsers()
      .then((res) => {
        if (res?.items) {
          setDemoUsers(res.items);
        }
        if (res?.default_password) {
          setDefaultPassword(res.default_password);
        }
      })
      .catch(() => {
        // Fallback nếu chưa kết nối
      });
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErrorMsg(null);
    setIsLoading(true);
    try {
      const res = await api.login(username.trim(), password);
      localStorage.setItem("ibanking_access_token", res.access_token);
      onLoginSuccess(res.user);
    } catch (err) {
      setErrorMsg(err.message || "Đăng nhập thất bại. Vui lòng kiểm tra lại.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleQuickSelect = (demoUser) => {
    setUsername(demoUser.username);
    setPassword(defaultPassword);
    setErrorMsg(null);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-blue-950 to-indigo-950 flex items-center justify-center p-4 sm:p-6">
      <div className="max-w-5xl w-full grid grid-cols-1 lg:grid-cols-12 bg-white rounded-3xl shadow-2xl overflow-hidden border border-white/10">
        {/* Left Banner: System Info & Demo Quick-Select */}
        <div className="lg:col-span-7 bg-gradient-to-br from-blue-900 via-blue-800 to-indigo-900 text-white p-8 flex flex-col justify-between">
          <div className="space-y-5">
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-2xl bg-white/15 border border-white/25 flex items-center justify-center shadow-inner">
                <Landmark className="w-7 h-7 text-amber-300" />
              </div>
              <div>
                <h1 className="text-2xl font-extrabold tracking-tight">
                  TDTU iBANKING
                </h1>
                <p className="text-xs text-blue-200">
                  Phân hệ Đóng học phí – Kiến Trúc Hướng Dịch Vụ (SOA 504070)
                </p>
              </div>
            </div>

            <div className="bg-white/10 backdrop-blur-sm rounded-2xl p-4 border border-white/15 space-y-2 text-xs text-blue-100">
              <div className="flex items-center gap-2 font-bold text-amber-300 text-sm">
                <ShieldCheck className="w-4 h-4" />
                <span>Kiến trúc Microservices & Đảm bảo Nhất quán Dữ liệu</span>
              </div>
              <p className="leading-relaxed">
                Hệ thống vận hành trên <strong>API Gateway (:8000)</strong> và{" "}
                <strong>4 Microservices độc lập</strong> (Database-per-Service
                trên PostgreSQL 16 + Redis 7 + Mailpit SMTP), hỗ trợ{" "}
                <strong>Pessimistic Locking</strong>,{" "}
                <strong>Saga Orchestration & Compensating Refund</strong>.
              </p>
            </div>

            {/* Demo Quick-Login Accounts */}
            <div className="space-y-2.5">
              <div className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-amber-300">
                  <Sparkles className="w-3.5 h-3.5" />
                  Chọn nhanh Tài khoản Mẫu để Demo (Mật khẩu: {defaultPassword})
                </span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                {demoUsers.map((u) => {
                  const isSelected = username === u.username;
                  return (
                    <button
                      key={u.id}
                      type="button"
                      onClick={() => handleQuickSelect(u)}
                      className={`text-left p-3 rounded-xl border transition-all ${
                        isSelected
                          ? "bg-white text-blue-950 border-amber-300 shadow-lg scale-[1.01]"
                          : "bg-blue-950/40 text-white border-white/15 hover:bg-white/10"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-sm">{u.full_name}</span>
                        <span
                          className={`text-[11px] font-mono px-2 py-0.5 rounded-full font-semibold ${
                            isSelected
                              ? "bg-blue-100 text-blue-900"
                              : "bg-white/10 text-blue-200"
                          }`}
                        >
                          {u.username}
                        </span>
                      </div>
                      <div
                        className={`flex items-center gap-1 text-xs font-bold mt-1.5 ${
                          isSelected ? "text-emerald-700" : "text-amber-300"
                        }`}
                      >
                        <Wallet className="w-3.5 h-3.5" />
                        <span>{formatCurrency(u.available_balance)}</span>
                      </div>
                      <p
                        className={`text-[11px] mt-0.5 truncate ${
                          isSelected ? "text-slate-500" : "text-blue-200"
                        }`}
                      >
                        {u.email}
                      </p>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="pt-5 text-[11px] text-blue-200 border-t border-white/10 mt-6 space-y-1.5">
            <div className="font-semibold text-amber-300">
              Nhóm thực hiện: Trần Minh Nghĩa - 524K0032 | Huỳnh Trung Tín - 524K0033 | Phan Nguyễn Thảo Như - 524V0007
            </div>
            <div className="flex items-center justify-between text-blue-300">
              <span>Trường Đại học Tôn Đức Thắng (TDTU)</span>
              <span>Môn SOA (504070) – HK1 / 2026-2027</span>
            </div>
          </div>
        </div>

        {/* Right Form: Login */}
        <div className="lg:col-span-5 p-8 sm:p-10 flex flex-col justify-center bg-white">
          <div className="mb-6">
            <h2 className="text-2xl font-extrabold text-slate-900">
              Đăng nhập Hệ thống
            </h2>
            <p className="text-xs text-slate-500 mt-1">
              Sử dụng tài khoản iBanking để truy cập chức năng Thanh toán học phí
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-xs font-bold uppercase text-slate-700 mb-1.5">
                Tên đăng nhập (Username)
              </label>
              <div className="relative">
                <User className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  required
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Nhập username (VD: nguyenvana)"
                  className="w-full pl-10 pr-4 py-3 rounded-xl border border-slate-300 focus:border-blue-600 focus:ring-4 focus:ring-blue-100 outline-none text-sm font-medium transition"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-bold uppercase text-slate-700 mb-1.5">
                Mật khẩu (Password)
              </label>
              <div className="relative">
                <Lock className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Nhập mật khẩu"
                  className="w-full pl-10 pr-4 py-3 rounded-xl border border-slate-300 focus:border-blue-600 focus:ring-4 focus:ring-blue-100 outline-none text-sm font-medium transition"
                />
              </div>
            </div>

            {errorMsg && (
              <div className="bg-rose-50 border border-rose-200 text-rose-800 rounded-xl p-3 text-xs flex items-center gap-2 font-medium">
                <AlertCircle className="w-4 h-4 text-rose-600 shrink-0" />
                <span>{errorMsg}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-3.5 px-5 rounded-xl bg-blue-700 hover:bg-blue-800 disabled:bg-slate-400 text-white font-bold text-sm shadow-lg shadow-blue-700/20 flex items-center justify-center gap-2 transition"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Đang xác thực...</span>
                </>
              ) : (
                <>
                  <span>Đăng nhập iBanking</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
