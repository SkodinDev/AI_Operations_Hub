import os

import psycopg
from openai import OpenAI
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from fastapi.responses import FileResponse
from pydantic import BaseModel

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

deepseek_client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)


app = FastAPI()
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")


class Ticket(BaseModel):
    customer: str
    issue: str
    status: Literal["Open", "Resolved"] = "Open"


class StatusUpdate(BaseModel):
    status: Literal["Open", "Resolved"]

@app.get("/")
def home():
    return FileResponse("frontend/templates/index.html")


@app.get("/tickets")
def get_tickets():
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, customer, issue, status FROM tickets ORDER BY id"
            )

            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "customer": row[1],
            "issue": row[2],
            "status": row[3],
        }
        for row in rows
    ]


@app.post("/tickets")
def create_ticket(ticket: Ticket):
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tickets (customer, issue)
                VALUES (%s, %s)
                RETURNING id
                """,
                (ticket.customer, ticket.issue),
            )

            ticket_id = cursor.fetchone()[0]

    return {
        "message": "Ticket created successfully",
        "ticket": {
            "id": ticket_id,
            "customer": ticket.customer,
            "issue": ticket.issue,
        },
    }



@app.put("/tickets/{ticket_id}")
def update_ticket(ticket_id: int, ticket: Ticket):
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE tickets
                SET customer = %s, issue = %s, status = %s
                WHERE id = %s
                RETURNING id, customer, issue, status
                """,
                (
                    ticket.customer,
                    ticket.issue,
                    ticket.status,
                    ticket_id,
                ),
            )

            updated_ticket = cursor.fetchone()

    if updated_ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    return {
        "message": "Ticket updated successfully",
        "ticket": {
            "id": updated_ticket[0],
            "customer": updated_ticket[1],
            "issue": updated_ticket[2],
            "status": updated_ticket[3],
        },
    }




@app.delete("/tickets/{ticket_id}")
def delete_ticket(ticket_id: int):
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM tickets
                WHERE id = %s
                RETURNING id
                """,
                (ticket_id,),
            )

            deleted_ticket = cursor.fetchone()

    if deleted_ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    return {
        "message": "Ticket deleted successfully",
        "ticket_id": deleted_ticket[0],
    }

@app.get("/stats")
def get_stats():
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'Open') AS open,
                    COUNT(*) FILTER (WHERE status = 'Resolved') AS resolved
                FROM tickets
                """
            )

            stats = cursor.fetchone()

    return {
        "total_tickets": stats[0],
        "open_tickets": stats[1],
        "resolved_tickets": stats[2],
    }



@app.put("/tickets/{ticket_id}/status")
def change_ticket_status(ticket_id: int, update: StatusUpdate):
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE tickets
                SET status = %s
                WHERE id = %s
                RETURNING id, customer, issue, status
                """,
                (update.status, ticket_id),
            )

            updated_ticket = cursor.fetchone()

    if updated_ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    return {
        "message": "Ticket status updated successfully",
        "ticket": {
            "id": updated_ticket[0],
            "customer": updated_ticket[1],
            "issue": updated_ticket[2],
            "status": updated_ticket[3],
        },
    }



def get_all_tickets():
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, customer, issue, status
                FROM tickets
                ORDER BY id
                """
            )

            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "customer": row[1],
            "issue": row[2],
            "status": row[3],
        }
        for row in rows
    ]



@app.get("/ask-ai")
def ask_ai(question: str):

    tickets = get_all_tickets()

    response = deepseek_client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {
                "role": "system",
                "content": f"""
You are an AI customer support assistant.

Here are the current customer support tickets:

{tickets}

Use these tickets when answering the user's question.
If the information is not available in the tickets, say so clearly.
"""
            },
            {
                "role": "user",
                "content": question
            }
        ]
    )

    answer = response.choices[0].message.content

    return {
        "question": question,
        "answer": answer
    }


@app.get("/tickets/{ticket_id}/ai-summary")
def ai_ticket_summary(ticket_id: int):

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, customer, issue, status
                FROM tickets
                WHERE id = %s
                """,
                (ticket_id,)
            )

            ticket = cursor.fetchone()

    if ticket is None:
        return {"message": "Ticket not found"}

    ticket_data = {
        "id": ticket[0],
        "customer": ticket[1],
        "issue": ticket[2],
        "status": ticket[3]
    }

    response = deepseek_client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {
                "role": "system",
                "content": """
You are a customer support assistant.

Analyze the ticket provided by the system.

Give:
1. A short summary of the customer's problem.
2. The likely next step for the support team.
3. A professional suggested reply to the customer.
"""
            },
            {
                "role": "user",
                "content": str(ticket_data)
            }
        ]
    )

    answer = response.choices[0].message.content

    return {
        "ticket": ticket_data,
        "ai_summary": answer
    }

