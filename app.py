
import os
import sqlite3

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash
)

app = Flask(__name__)
app.secret_key = "smart_workload_manager_secret_key"

# Always store the database beside app.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "smart_workload.db")


# --------------------------------------------------
# DATABASE CONNECTION
# --------------------------------------------------

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# --------------------------------------------------
# CREATE DATABASE TABLES
# --------------------------------------------------

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            capacity REAL NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            project_id INTEGER NOT NULL,
            member_id INTEGER,
            hours REAL NOT NULL,
            priority TEXT NOT NULL,
            deadline TEXT,
            status TEXT DEFAULT 'Pending',
            FOREIGN KEY (project_id)
                REFERENCES projects(id),
            FOREIGN KEY (member_id)
                REFERENCES members(id)
                ON DELETE SET NULL
        )
    """)

    conn.commit()
    conn.close()


# --------------------------------------------------
# WORKLOAD CALCULATION
# --------------------------------------------------

def get_member_workload(cursor, member_id):
    cursor.execute("""
        SELECT COALESCE(SUM(hours), 0) AS total
        FROM tasks
        WHERE member_id = ?
        AND status != 'Completed'
    """, (member_id,))

    result = cursor.fetchone()
    return float(result["total"] or 0)


def get_all_members(cursor):
    cursor.execute("SELECT * FROM members ORDER BY id DESC")
    member_rows = cursor.fetchall()

    members = []

    for member in member_rows:

        assigned = get_member_workload(cursor, member["id"])
        capacity = float(member["capacity"])

        percentage = (
            round((assigned / capacity) * 100)
            if capacity > 0 else 0
        )

        if percentage < 70:
            status = "Available"
        elif percentage <= 100:
            status = "Busy"
        else:
            status = "Overloaded"

        members.append({
            "id": member["id"],
            "name": member["name"],
            "role": member["role"],
            "capacity": capacity,
            "assigned": round(assigned, 2),
            "percentage": percentage,
            "status": status
        })

    return members


# --------------------------------------------------
# SMART TASK ASSIGNMENT
# --------------------------------------------------

def smart_assign_member(cursor, hours):

    cursor.execute("SELECT * FROM members")

    members = cursor.fetchall()

    if not members:
        return None

    best_member = None
    lowest_workload = None

    for member in members:

        assigned = get_member_workload(cursor, member["id"])
        capacity = float(member["capacity"])

        if assigned + hours <= capacity:

            if (
                lowest_workload is None
                or assigned < lowest_workload
            ):
                lowest_workload = assigned
                best_member = member["id"]

    # If no member has enough remaining capacity,
    # assign the task to the least-loaded member.
    if best_member is None:

        for member in members:

            assigned = get_member_workload(
                cursor, member["id"]
            )

            if (
                lowest_workload is None
                or assigned < lowest_workload
            ):
                lowest_workload = assigned
                best_member = member["id"]

    return best_member


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

@app.route("/")
def dashboard():

    conn = get_db()
    cursor = conn.cursor()

    # Members and workload
    members = get_all_members(cursor)

    # Projects
    cursor.execute("""
        SELECT * FROM projects
        ORDER BY id DESC
    """)
    projects = cursor.fetchall()

    # Tasks with project and member names
    cursor.execute("""
        SELECT
            tasks.*,
            projects.name AS project_name,
            members.name AS member_name
        FROM tasks
        LEFT JOIN projects
            ON tasks.project_id = projects.id
        LEFT JOIN members
            ON tasks.member_id = members.id
        ORDER BY tasks.id DESC
    """)

    tasks = cursor.fetchall()

    # Dashboard statistics
    total_tasks = len(tasks)

    completed = sum(
        1 for task in tasks
        if task["status"] == "Completed"
    )

    pending = total_tasks - completed

    overloaded = sum(
        1 for member in members
        if member["status"] == "Overloaded"
    )

    progress = (
        round((completed / total_tasks) * 100)
        if total_tasks > 0 else 0
    )

    # Chart information
    chart_names = [
        member["name"] for member in members
    ]

    chart_percentages = [
        member["percentage"] for member in members
    ]

    conn.close()

    return render_template(
        "index.html",
        members=members,
        projects=projects,
        tasks=tasks,
        total_tasks=total_tasks,
        completed=completed,
        pending=pending,
        overloaded=overloaded,
        progress=progress,
        chart_names=chart_names,
        chart_percentages=chart_percentages
    )


# --------------------------------------------------
# ADD TEAM MEMBER
# --------------------------------------------------

@app.route("/add_member", methods=["POST"])
def add_member():

    name = request.form.get("name", "").strip()
    role = request.form.get("role", "").strip()

    try:
        capacity = float(request.form.get("capacity", 0))

        if not name or not role or capacity <= 0:
            raise ValueError

    except (ValueError, TypeError):
        flash("Please enter valid member details!", "error")
        return redirect("/")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO members (name, role, capacity)
        VALUES (?, ?, ?)
    """, (name, role, capacity))

    conn.commit()
    conn.close()

    flash("Team member added successfully!", "success")
    return redirect("/")


# --------------------------------------------------
# EDIT TEAM MEMBER
# --------------------------------------------------

@app.route(
    "/edit_member/<int:member_id>",
    methods=["GET", "POST"]
)
def edit_member(member_id):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM members WHERE id = ?",
        (member_id,)
    )

    member = cursor.fetchone()

    if member is None:
        conn.close()
        flash("Member not found!", "error")
        return redirect("/")

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        role = request.form.get("role", "").strip()

        try:
            capacity = float(
                request.form.get("capacity", 0)
            )

            if not name or not role or capacity <= 0:
                raise ValueError

        except (ValueError, TypeError):
            conn.close()
            flash("Please enter valid member details!", "error")
            return redirect(
                url_for("edit_member", member_id=member_id)
            )

        cursor.execute("""
            UPDATE members
            SET name = ?, role = ?, capacity = ?
            WHERE id = ?
        """, (name, role, capacity, member_id))

        conn.commit()
        conn.close()

        flash("Member updated successfully!", "success")
        return redirect("/")

    conn.close()

    return render_template(
        "edit_member.html",
        member=member
    )


# --------------------------------------------------
# DELETE TEAM MEMBER
# --------------------------------------------------

@app.route(
    "/delete_member/<int:member_id>",
    methods=["POST"]
)
def delete_member(member_id):

    conn = get_db()
    cursor = conn.cursor()

    # Keep tasks, but remove their member assignment
    cursor.execute("""
        UPDATE tasks
        SET member_id = NULL
        WHERE member_id = ?
    """, (member_id,))

    cursor.execute(
        "DELETE FROM members WHERE id = ?",
        (member_id,)
    )

    conn.commit()
    conn.close()

    flash("Team member deleted successfully!", "success")
    return redirect("/")


# --------------------------------------------------
# ADD PROJECT
# --------------------------------------------------

@app.route("/add_project", methods=["POST"])
def add_project():

    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()

    if not name:
        flash("Project name is required!", "error")
        return redirect("/")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO projects (name, description)
        VALUES (?, ?)
    """, (name, description))

    conn.commit()
    conn.close()

    flash("Project created successfully!", "success")
    return redirect("/")


# --------------------------------------------------
# EDIT PROJECT
# --------------------------------------------------

@app.route(
    "/edit_project/<int:project_id>",
    methods=["GET", "POST"]
)
def edit_project(project_id):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM projects WHERE id = ?",
        (project_id,)
    )

    project = cursor.fetchone()

    if project is None:
        conn.close()
        flash("Project not found!", "error")
        return redirect("/")

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()

        if not name:
            conn.close()
            flash("Project name cannot be empty!", "error")
            return redirect(
                url_for("edit_project", project_id=project_id)
            )

        cursor.execute("""
            UPDATE projects
            SET name = ?, description = ?
            WHERE id = ?
        """, (name, description, project_id))

        conn.commit()
        conn.close()

        flash("Project updated successfully!", "success")
        return redirect("/")

    conn.close()

    return render_template(
        "edit_project.html",
        project=project
    )


# --------------------------------------------------
# DELETE PROJECT
# --------------------------------------------------

@app.route(
    "/delete_project/<int:project_id>",
    methods=["POST"]
)
def delete_project(project_id):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM projects WHERE id = ?",
        (project_id,)
    )

    project = cursor.fetchone()

    if project is None:
        conn.close()
        flash("Project not found!", "error")
        return redirect("/")

    # Delete associated tasks first
    cursor.execute("""
        DELETE FROM tasks
        WHERE project_id = ?
    """, (project_id,))

    # Delete project
    cursor.execute("""
        DELETE FROM projects
        WHERE id = ?
    """, (project_id,))

    conn.commit()
    conn.close()

    flash(
        "Project and its associated tasks deleted successfully!",
        "success"
    )

    return redirect("/")


# --------------------------------------------------
# ADD TASK
# --------------------------------------------------

@app.route("/add_task", methods=["POST"])
def add_task():

    title = request.form.get("title", "").strip()
    project_id = request.form.get("project_id")
    member_id = request.form.get("member_id")
    priority = request.form.get("priority")
    deadline = request.form.get("deadline")

    try:
        hours = float(request.form.get("hours", 0))
        project_id = int(project_id)

        if not title or hours <= 0:
            raise ValueError

        if priority not in ["Low", "Medium", "High"]:
            raise ValueError

    except (ValueError, TypeError):
        flash("Please enter valid task details!", "error")
        return redirect("/")

    conn = get_db()
    cursor = conn.cursor()

    # Verify project exists
    cursor.execute(
        "SELECT id FROM projects WHERE id = ?",
        (project_id,)
    )

    if cursor.fetchone() is None:
        conn.close()
        flash("Please select a valid project!", "error")
        return redirect("/")

    # Smart assignment if member not selected
    if member_id:

        try:
            member_id = int(member_id)

            cursor.execute(
                "SELECT id FROM members WHERE id = ?",
                (member_id,)
            )

            if cursor.fetchone() is None:
                raise ValueError

        except (ValueError, TypeError):
            conn.close()
            flash("Please select a valid team member!", "error")
            return redirect("/")

    else:
        member_id = smart_assign_member(cursor, hours)

    cursor.execute("""
        INSERT INTO tasks (
            title,
            project_id,
            member_id,
            hours,
            priority,
            deadline,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, 'Pending')
    """, (
        title,
        project_id,
        member_id,
        hours,
        priority,
        deadline,
    ))

    conn.commit()
    conn.close()

    flash("Task created successfully!", "success")
    return redirect("/")


# --------------------------------------------------
# EDIT TASK
# --------------------------------------------------

@app.route(
    "/edit_task/<int:task_id>",
    methods=["GET", "POST"]
)
def edit_task(task_id):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM tasks WHERE id = ?",
        (task_id,)
    )

    task = cursor.fetchone()

    if task is None:
        conn.close()
        flash("Task not found!", "error")
        return redirect("/")

    if request.method == "POST":

        title = request.form.get("title", "").strip()
        project_id = request.form.get("project_id")
        member_id = request.form.get("member_id")
        priority = request.form.get("priority")
        deadline = request.form.get("deadline")
        status = request.form.get("status")

        try:
            hours = float(request.form.get("hours", 0))
            project_id = int(project_id)

            if not title or hours <= 0:
                raise ValueError

            if priority not in ["Low", "Medium", "High"]:
                raise ValueError

            if status not in [
                "Pending",
                "In Progress",
                "Completed"
            ]:
                raise ValueError

            cursor.execute(
                "SELECT id FROM projects WHERE id = ?",
                (project_id,)
            )

            if cursor.fetchone() is None:
                raise ValueError

            if member_id:
                member_id = int(member_id)

                cursor.execute(
                    "SELECT id FROM members WHERE id = ?",
                    (member_id,)
                )

                if cursor.fetchone() is None:
                    raise ValueError
            else:
                member_id = None

        except (ValueError, TypeError):
            conn.close()
            flash("Please enter valid task details!", "error")
            return redirect(
                url_for("edit_task", task_id=task_id)
            )

        cursor.execute("""
            UPDATE tasks
            SET
                title = ?,
                project_id = ?,
                member_id = ?,
                hours = ?,
                priority = ?,
                deadline = ?,
                status = ?
            WHERE id = ?
        """, (
            title,
            project_id,
            member_id,
            hours,
            priority,
            deadline,
            status,
            task_id
        ))

        conn.commit()
        conn.close()

        flash("Task updated successfully!", "success")
        return redirect("/")

    cursor.execute("""
        SELECT * FROM projects ORDER BY name
    """)
    projects = cursor.fetchall()

    cursor.execute("""
        SELECT * FROM members ORDER BY name
    """)
    members = cursor.fetchall()

    conn.close()

    return render_template(
        "edit_task.html",
        task=task,
        projects=projects,
        members=members
    )


# --------------------------------------------------
# UPDATE TASK STATUS
# --------------------------------------------------

@app.route(
    "/update_task/<int:task_id>",
    methods=["POST"]
)
def update_task(task_id):

    status = request.form.get("status")

    if status not in [
        "Pending",
        "In Progress",
        "Completed"
    ]:
        flash("Invalid task status!", "error")
        return redirect("/")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE tasks
        SET status = ?
        WHERE id = ?
    """, (status, task_id))

    conn.commit()
    conn.close()

    flash("Task status updated successfully!", "success")
    return redirect("/")


# --------------------------------------------------
# DELETE TASK
# --------------------------------------------------

@app.route(
    "/delete_task/<int:task_id>",
    methods=["POST"]
)
def delete_task(task_id):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM tasks
        WHERE id = ?
    """, (task_id,))

    deleted = cursor.rowcount

    conn.commit()
    conn.close()

    if deleted:
        flash("Task deleted successfully!", "success")
    else:
        flash("Task not found!", "error")

    # Redirect to dashboard without relying on endpoint name
    return redirect("/")


# --------------------------------------------------
# RUN APPLICATION
# --------------------------------------------------

# Initialize database when the application starts
init_db()

if __name__ == "__main__":
    app.run(debug=True)
