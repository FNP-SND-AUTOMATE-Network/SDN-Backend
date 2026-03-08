"""
Slack Incoming Webhook Client
ส่งข้อความแจ้งเตือนไปยัง Slack Channel ผ่าน Incoming Webhook

รองรับ:
  - Plain text messages
  - Block Kit (rich formatting) messages
  - Async with retry
"""

import httpx
from typing import Any, Dict, List, Optional
from app.core.logging import logger
from app.core.config import settings


class SlackClient:
    """HTTP client for Slack Incoming Webhooks."""

    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or settings.SLACK_WEBHOOK_URL
        self.timeout = httpx.Timeout(10.0, connect=5.0)
        self.max_retries = 2

    async def send_message(self, text: str, blocks: Optional[List[Dict]] = None) -> bool:
        """
        ส่งข้อความไปยัง Slack

        Args:
            text: Fallback text (แสดงเมื่อ client ไม่รองรับ blocks)
            blocks: Block Kit blocks สำหรับ rich formatting

        Returns:
            True ถ้าส่งสำเร็จ
        """
        if not self.webhook_url:
            logger.warning("[Slack] No webhook URL configured — skipping notification")
            return False

        payload: Dict[str, Any] = {"text": text}
        if blocks:
            payload["blocks"] = blocks

        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(self.webhook_url, json=payload)

                if response.status_code == 200 and response.text == "ok":
                    logger.info(f"[Slack] Message sent successfully (attempt {attempt})")
                    return True
                else:
                    logger.warning(
                        f"[Slack] Unexpected response (attempt {attempt}): "
                        f"status={response.status_code}, body={response.text[:200]}"
                    )
            except httpx.TimeoutException:
                logger.warning(f"[Slack] Timeout on attempt {attempt}/{self.max_retries}")
            except Exception as exc:
                logger.error(f"[Slack] Send failed (attempt {attempt}): {exc}")

        logger.error("[Slack] All retry attempts exhausted — message not sent")
        return False

    async def send_block_message(
        self,
        header: str,
        body_lines: List[str],
        color: str = "#36a64f",
        footer: Optional[str] = None,
    ) -> bool:
        """
        ส่ง Block Kit message แบบมีโครงสร้าง

        Args:
            header: หัวข้อข้อความ
            body_lines: รายการข้อความในส่วน body
            color: สี accent (ไม่ได้ใช้ตรงใน blocks แต่ใช้เป็น indicator)
            footer: ข้อความท้าย (optional)
        """
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": header,
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "\n".join(body_lines),
                },
            },
        ]

        if footer:
            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": footer}
                    ],
                }
            )

        return await self.send_message(text=header, blocks=blocks)

    async def test_connection(self) -> Dict[str, Any]:
        """ทดสอบการเชื่อมต่อ Slack Webhook"""
        if not self.webhook_url:
            return {
                "status": "error",
                "message": "SLACK_WEBHOOK_URL is not configured",
            }

        success = await self.send_message(
            text="🔧 SDN ChatOps — Connection Test",
            blocks=[
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "🔧 SDN ChatOps — Connection Test",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "✅ *Slack integration is working!*\n\n"
                            "This message confirms that the SDN Backend "
                            "can send notifications to this channel."
                        ),
                    },
                },
                {"type": "divider"},
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "🤖 _SDN ChatOps Engine · Network Fault Management_",
                        }
                    ],
                },
            ],
        )

        return {
            "status": "ok" if success else "error",
            "message": "Test message sent to Slack" if success else "Failed to send test message",
            "webhook_configured": bool(self.webhook_url),
        }
