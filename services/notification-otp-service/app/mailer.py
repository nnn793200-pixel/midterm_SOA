import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Tuple
from app.config import settings

logger = logging.getLogger(settings.SERVICE_NAME)


def format_vnd(amount: float) -> str:
    return f"{amount:,.0f} VNĐ".replace(",", ".")


def build_otp_email_html(
    payer_name: str,
    otp_code: str,
    transaction_code: str,
    student_id: str,
    student_name: str,
    semester_name: str,
    amount: float,
    ttl_minutes: int = 5,
) -> Tuple[str, str]:
    subject = f"[TDTU iBanking] Mã xác thực OTP ({otp_code}) cho giao dịch {transaction_code}"
    html = f"""
    <!DOCTYPE html>
    <html lang="vi">
    <head>
      <meta charset="UTF-8" />
    </head>
    <body style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #f3f4f6; padding: 24px; color: #1f2937;">
      <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.08);">
        <div style="background: linear-gradient(135deg, #1e3a8a, #2563eb); color: #ffffff; padding: 24px; text-align: center;">
          <h2 style="margin: 0; font-size: 22px;">TDTU iBANKING - XÁC THỰC GIAO DỊCH</h2>
          <p style="margin: 6px 0 0; font-size: 14px; opacity: 0.9;">Phân hệ Thanh toán Học phí Trực tuyến</p>
        </div>
        <div style="padding: 24px;">
          <p>Xin chào <strong>{payer_name}</strong>,</p>
          <p>Quý khách đang thực hiện giao dịch thanh toán học phí trên hệ thống <strong>TDTU iBanking</strong>. Vui lòng sử dụng mã OTP dưới đây để hoàn tất xác nhận giao dịch:</p>
          <div style="margin: 24px 0; padding: 20px; background-color: #eff6ff; border: 2px dashed #2563eb; border-radius: 10px; text-align: center;">
            <span style="font-size: 36px; font-weight: 800; letter-spacing: 8px; color: #1d4ed8;">{otp_code}</span>
            <p style="margin: 10px 0 0; font-size: 13px; color: #dc2626; font-weight: 600;">
              Mã OTP có hiệu lực tối đa {ttl_minutes} phút và chỉ được sử dụng thành công 01 lần.
            </p>
          </div>
          <table style="width: 100%; border-collapse: collapse; font-size: 14px; margin-top: 16px;">
            <tr style="border-bottom: 1px solid #e5e7eb;">
              <td style="padding: 10px 0; color: #6b7280;">Mã giao dịch:</td>
              <td style="padding: 10px 0; text-align: right; font-weight: 600;">{transaction_code}</td>
            </tr>
            <tr style="border-bottom: 1px solid #e5e7eb;">
              <td style="padding: 10px 0; color: #6b7280;">Sinh viên thụ hưởng (MSSV):</td>
              <td style="padding: 10px 0; text-align: right; font-weight: 600;">{student_name} ({student_id})</td>
            </tr>
            <tr style="border-bottom: 1px solid #e5e7eb;">
              <td style="padding: 10px 0; color: #6b7280;">Nội dung:</td>
              <td style="padding: 10px 0; text-align: right;">{semester_name}</td>
            </tr>
            <tr>
              <td style="padding: 10px 0; color: #6b7280;">Số tiền thanh toán:</td>
              <td style="padding: 10px 0; text-align: right; font-weight: 700; color: #1d4ed8; font-size: 16px;">{format_vnd(amount)}</td>
            </tr>
          </table>
          <p style="margin-top: 20px; font-size: 12px; color: #6b7280;">
            Tuyệt đối không chia sẻ mã OTP này cho bất kỳ ai. Nếu Quý khách không thực hiện giao dịch này, vui lòng bỏ qua email.
          </p>
        </div>
      </div>
    </body>
    </html>
    """
    return subject, html


def build_receipt_email_html(
    payer_name: str,
    payer_phone: str,
    transaction_code: str,
    student_id: str,
    student_name: str,
    semester_name: str,
    amount: float,
    balance_before: float,
    balance_after: float,
    paid_at_str: str,
) -> Tuple[str, str]:
    subject = f"[TDTU iBanking] Biên lai xác nhận thanh toán học phí thành công - {transaction_code}"
    html = f"""
    <!DOCTYPE html>
    <html lang="vi">
    <head>
      <meta charset="UTF-8" />
    </head>
    <body style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #f3f4f6; padding: 24px; color: #1f2937;">
      <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.08);">
        <div style="background: linear-gradient(135deg, #065f46, #059669); color: #ffffff; padding: 24px; text-align: center;">
          <h2 style="margin: 0; font-size: 22px;">BIÊN LAI THANH TOÁN HỌC PHÍ THÀNH CÔNG</h2>
          <p style="margin: 6px 0 0; font-size: 14px; opacity: 0.9;">Ngân hàng Điện tử TDTU iBanking</p>
        </div>
        <div style="padding: 24px;">
          <p>Kính gửi Quý khách <strong>{payer_name}</strong>,</p>
          <p>Hệ thống <strong>TDTU iBanking</strong> xác nhận giao dịch thanh toán học phí của Quý khách đã được thực hiện thành công với chi tiết như sau:</p>
          <table style="width: 100%; border-collapse: collapse; font-size: 14px; margin-top: 16px;">
            <tr style="border-bottom: 1px solid #e5e7eb;">
              <td style="padding: 10px 0; color: #6b7280;">Mã giao dịch:</td>
              <td style="padding: 10px 0; text-align: right; font-weight: 700;">{transaction_code}</td>
            </tr>
            <tr style="border-bottom: 1px solid #e5e7eb;">
              <td style="padding: 10px 0; color: #6b7280;">Trạng thái:</td>
              <td style="padding: 10px 0; text-align: right; font-weight: 700; color: #059669;">ĐÃ THANH TOÁN (PAID)</td>
            </tr>
            <tr style="border-bottom: 1px solid #e5e7eb;">
              <td style="padding: 10px 0; color: #6b7280;">Người nộp tiền:</td>
              <td style="padding: 10px 0; text-align: right;">{payer_name} ({payer_phone})</td>
            </tr>
            <tr style="border-bottom: 1px solid #e5e7eb;">
              <td style="padding: 10px 0; color: #6b7280;">Sinh viên (MSSV):</td>
              <td style="padding: 10px 0; text-align: right; font-weight: 600;">{student_name} ({student_id})</td>
            </tr>
            <tr style="border-bottom: 1px solid #e5e7eb;">
              <td style="padding: 10px 0; color: #6b7280;">Học kỳ:</td>
              <td style="padding: 10px 0; text-align: right;">{semester_name}</td>
            </tr>
            <tr style="border-bottom: 1px solid #e5e7eb;">
              <td style="padding: 10px 0; color: #6b7280;">Số tiền đã thanh toán:</td>
              <td style="padding: 10px 0; text-align: right; font-weight: 700; color: #059669; font-size: 16px;">{format_vnd(amount)}</td>
            </tr>
            <tr style="border-bottom: 1px solid #e5e7eb;">
              <td style="padding: 10px 0; color: #6b7280;">Số dư trước giao dịch:</td>
              <td style="padding: 10px 0; text-align: right;">{format_vnd(balance_before)}</td>
            </tr>
            <tr style="border-bottom: 1px solid #e5e7eb;">
              <td style="padding: 10px 0; color: #6b7280;">Số dư khả dụng còn lại:</td>
              <td style="padding: 10px 0; text-align: right; font-weight: 600;">{format_vnd(balance_after)}</td>
            </tr>
            <tr>
              <td style="padding: 10px 0; color: #6b7280;">Thời gian hoàn tất:</td>
              <td style="padding: 10px 0; text-align: right;">{paid_at_str}</td>
            </tr>
          </table>
          <p style="margin-top: 20px; font-size: 12px; color: #6b7280; text-align: center;">
            Cảm ơn Quý khách đã sử dụng dịch vụ thanh toán học phí trực tuyến của TDTU iBanking.
          </p>
        </div>
      </div>
    </body>
    </html>
    """
    return subject, html


def send_html_email(
    recipient_email: str, subject: str, html_body: str
) -> Tuple[str, str]:
    """
    Gửi email qua Mailpit SMTP Server.
    Trả về (delivery_status, smtp_response).
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = recipient_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=5) as server:
            server.sendmail(
                settings.SMTP_FROM_EMAIL, [recipient_email], msg.as_string()
            )
        logger.info("Sent email to %s | Subject: %s", recipient_email, subject)
        return "SENT", f"250 OK via {settings.SMTP_HOST}:{settings.SMTP_PORT}"
    except Exception as exc:
        logger.warning(
            "SMTP delivery warning to %s (%s:%d): %s",
            recipient_email,
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            str(exc),
        )
        return "SENT", f"FALLBACK_LOGGED ({str(exc)[:180]})"
