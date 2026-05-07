"""
MediaPresence model — thin data-access helpers for the media_presence table.
"""

from backend.utils.database import get_db_cursor


def _row_to_dict(row):
    if not row:
        return None
    out = dict(row)
    # Normalise dates/times to ISO strings for JSON
    for k in ("event_date", "event_time", "created_at", "updated_at"):
        if out.get(k) is not None:
            out[k] = out[k].isoformat() if hasattr(out[k], "isoformat") else out[k]
    return out


class MediaPresence:
    @staticmethod
    def list_all(limit=200, offset=0, transcribe_status=None, rationale_status=None,
                 created_by=None):
        sql = """
            SELECT mp.*, c.channel_name, c.channel_logo_path,
                   sr.unsigned_pdf_path, sr.signed_pdf_path, sr.sign_status
            FROM media_presence mp
            LEFT JOIN channels c ON mp.channel_id = c.id
            LEFT JOIN saved_rationale sr ON sr.job_id = mp.rationale_job_id
            WHERE 1=1
        """
        params = []
        if transcribe_status:
            sql += " AND mp.transcribe_status = %s"
            params.append(transcribe_status)
        if rationale_status:
            sql += " AND mp.rationale_status = %s"
            params.append(rationale_status)
        if created_by is not None:
            sql += " AND mp.created_by = %s"
            params.append(created_by)
        sql += " ORDER BY mp.event_date DESC, mp.event_time DESC, mp.id DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        with get_db_cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        return [_row_to_dict(r) for r in rows]

    @staticmethod
    def get(media_id):
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                SELECT mp.*, c.channel_name, c.channel_logo_path,
                       sr.unsigned_pdf_path, sr.signed_pdf_path, sr.sign_status
                FROM media_presence mp
                LEFT JOIN channels c ON mp.channel_id = c.id
                LEFT JOIN saved_rationale sr ON sr.job_id = mp.rationale_job_id
                WHERE mp.id = %s
                """,
                (media_id,),
            )
            row = cursor.fetchone()
        return _row_to_dict(row)

    @staticmethod
    def create(payload, created_by):
        with get_db_cursor(commit=True) as cursor:
            cursor.execute(
                """
                INSERT INTO media_presence (
                    platform, channel_id, event_date, event_time,
                    video_url, video_title, rationale_tool, notes, created_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    payload.get("platform"),
                    payload.get("channel_id"),
                    payload.get("event_date"),
                    payload.get("event_time"),
                    payload.get("video_url"),
                    payload.get("video_title"),
                    payload.get("rationale_tool"),
                    payload.get("notes"),
                    created_by,
                ),
            )
            new_id = cursor.fetchone()["id"]
        return MediaPresence.get(new_id)

    @staticmethod
    def update(media_id, payload):
        # Only allow editing safe fields
        allowed = (
            "platform", "channel_id", "event_date", "event_time",
            "video_url", "video_title", "rationale_tool", "notes",
        )
        sets, params = [], []
        for k in allowed:
            if k in payload:
                sets.append(f"{k} = %s")
                params.append(payload[k])
        if not sets:
            return MediaPresence.get(media_id)
        sets.append("updated_at = CURRENT_TIMESTAMP")
        params.append(media_id)
        with get_db_cursor(commit=True) as cursor:
            cursor.execute(
                f"UPDATE media_presence SET {', '.join(sets)} WHERE id = %s",
                params,
            )
        return MediaPresence.get(media_id)

    @staticmethod
    def delete(media_id):
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("DELETE FROM media_presence WHERE id = %s", (media_id,))
            return cursor.rowcount > 0
