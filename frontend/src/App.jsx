import React, { useState, useEffect, useCallback } from "react";
import { api } from "./api/client";
import Navbar from "./components/Navbar";
import LoginPage from "./pages/LoginPage";
import TuitionPaymentPage from "./pages/TuitionPaymentPage";
import TransactionHistoryPage from "./pages/TransactionHistoryPage";

export default function App() {
  const [user, setUser] = useState(null);
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);
  const [activeTab, setActiveTab] = useState("payment");
  const [isResetting, setIsResetting] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [toastMsg, setToastMsg] = useState(null);

  const showToast = (msg) => {
    setToastMsg(msg);
    setTimeout(() => {
      setToastMsg(null);
    }, 4000);
  };

  const refreshUserProfile = useCallback(async () => {
    const token = localStorage.getItem("ibanking_access_token");
    if (!token) {
      setUser(null);
      setIsCheckingAuth(false);
      return;
    }
    try {
      const profile = await api.getMyAccount();
      setUser(profile);
    } catch {
      localStorage.removeItem("ibanking_access_token");
      setUser(null);
    } finally {
      setIsCheckingAuth(false);
    }
  }, []);

  useEffect(() => {
    refreshUserProfile();
  }, [refreshUserProfile]);

  const handleLogout = () => {
    localStorage.removeItem("ibanking_access_token");
    setUser(null);
    setActiveTab("payment");
  };

  const handleResetDemo = async () => {
    setIsResetting(true);
    try {
      await api.resetDemoSystem();
      await refreshUserProfile();
      setRefreshTrigger((prev) => prev + 1);
      showToast(
        "Đã khôi phục số dư mặc định & trạng thái học phí UNPAID trên cả 4 Microservices!"
      );
    } catch (err) {
      showToast(`Lỗi khi reset dữ liệu mẫu: ${err.message}`);
    } finally {
      setIsResetting(false);
    }
  };

  if (isCheckingAuth) {
    return (
      <div className="min-h-screen bg-slate-900 text-white flex items-center justify-center text-sm font-semibold">
        Đang tải phiên làm việc TDTU iBanking...
      </div>
    );
  }

  if (!user) {
    return (
      <LoginPage
        onLoginSuccess={(loggedInUser) => {
          setUser(loggedInUser);
          setActiveTab("payment");
        }}
      />
    );
  }

  return (
    <div className="min-h-screen flex flex-col bg-slate-100">
      <Navbar
        user={user}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onLogout={handleLogout}
        onResetDemo={handleResetDemo}
        isResetting={isResetting}
      />

      {toastMsg && (
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-4 w-full">
          <div className="bg-emerald-800 text-white px-4 py-3 rounded-xl shadow-md text-xs font-bold flex items-center justify-between">
            <span>✓ {toastMsg}</span>
            <button
              type="button"
              onClick={() => setToastMsg(null)}
              className="text-emerald-200 hover:text-white ml-4"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {activeTab === "payment" ? (
          <TuitionPaymentPage
            user={user}
            onRefreshUser={refreshUserProfile}
            onNavigateHistory={() => setActiveTab("history")}
            refreshTrigger={refreshTrigger}
          />
        ) : (
          <TransactionHistoryPage
            user={user}
            refreshTrigger={refreshTrigger}
          />
        )}
      </main>

      <footer className="bg-white border-t border-slate-200 py-3.5 px-4 text-center text-xs text-slate-600 space-y-1">
        <div className="font-semibold text-slate-800">
          Nhóm thực hiện: Trần Minh Nghĩa - 524K0032 | Huỳnh Trung Tín - 524K0033 | Phan Nguyễn Thảo Như - 524V0007
        </div>
        <div className="text-slate-500">
          TDTU iBanking – Dự án Giữa kỳ Môn Kiến Trúc Hướng Dịch Vụ (504070) •
          API Gateway (:8000) • Auth-Account (:8001) • Tuition (:8002) • Payment
          Saga (:8003) • Notification-OTP (:8004)
        </div>
      </footer>
    </div>
  );
}
