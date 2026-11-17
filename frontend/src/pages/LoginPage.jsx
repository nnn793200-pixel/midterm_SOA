import React, { useState } from "react";
import { Landmark, Lock, User, ArrowRight, AlertCircle, Loader2 } from "lucide-react";
import { api } from "../api/client";

export default function LoginPage({ onLoginSuccess }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

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

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-blue-950 to-indigo-950 flex items-center justify-center p-4 sm:p-6">
      <div className="max-w-4xl w-full grid grid-cols-1 lg:grid-cols-12 bg-white rounded-3xl shadow-2xl overflow-hidden border border-white/10">
        {/* Left Banner */}
        <div className="lg:col-span-6 bg-gradient-to-br from-blue-900 via-blue-800 to-indigo-900 text-white p-8 flex flex-col justify-between">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-2xl bg-white/15 border border-white/25 flex items-center justify-center shadow-inner">
              <Landmark className="w-7 h-7 text-amber-300" />
            </div>
            <div>
              <h1 className="text-2xl font-extrabold tracking-tight">
                TDTU iBANKING
              </h1>
              <p className="text-xs text-blue-200">
                Thanh toán học phí trực tuyến
              </p>
            </div>
          </div>

          <div className="pt-10 text-[11px] text-blue-200 space-y-1.5">
            <div className="font-semibold text-amber-300">
              Nhóm thực hiện: Trần Minh Nghĩa - 524K0032 | Huỳnh Trung Tín - 524K0033 | Phan Nguyễn Thảo Như - 524V0007
            </div>
            <div className="text-blue-300">
              Trường Đại học Tôn Đức Thắng • Môn Kiến Trúc Hướng Dịch Vụ (504070)
            </div>
          </div>
        </div>

        {/* Right Form: Login */}
        <div className="lg:col-span-6 p-8 sm:p-10 flex flex-col justify-center bg-white">
          <div className="mb-6">
            <h2 className="text-2xl font-extrabold text-slate-900">
              Đăng nhập
            </h2>
            <p className="text-xs text-slate-500 mt-1">
              Vui lòng đăng nhập để sử dụng dịch vụ thanh toán học phí
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-xs font-bold uppercase text-slate-700 mb-1.5">
                Tên đăng nhập
              </label>
              <div className="relative">
                <User className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  required
                  autoFocus
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Nhập tên đăng nhập"
                  className="w-full pl-10 pr-4 py-3 rounded-xl border border-slate-300 focus:border-blue-600 focus:ring-4 focus:ring-blue-100 outline-none text-sm font-medium transition"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-bold uppercase text-slate-700 mb-1.5">
                Mật khẩu
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
                  <span>Đăng nhập</span>
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
