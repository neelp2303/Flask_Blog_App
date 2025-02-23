import io
import os
from flask import Flask, request, render_template, redirect, send_file, session, g
import sqlite3
import bcrypt  # type: ignore
from flask_ngrok import run_with_ngrok
from werkzeug.utils import secure_filename
from slugify import slugify  # type: ignore

UPLOAD_FOLDER = "uploads"

app = Flask(__name__)
app.secret_key = "secret_key"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
DATABASE = "database.db"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# Function to get database connection
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row  # Return results as dictionaries
    return g.db


# Initialize Database
def init_db():
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        """
        )
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS blogs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        author TEXT NOT NULL,
                        email TEXT NOT NULL,
                        slug TEXT,
                        image_filename TEXT,
                        category_id INTEGER,
                        FOREIGN KEY (category_id) REFERENCES categories(id)
            
                        )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS blog_tags (
                blog_id INTEGER,
                tag_id INTEGER,
                PRIMARY KEY (blog_id, tag_id),
                FOREIGN KEY (blog_id) REFERENCES blogs(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            )
        """
        )

        conn.commit()
        # conn.close()


init_db()


@app.route("/get_image/<filename>")
def get_image(filename):
    return send_file(os.path.join(app.config["UPLOAD_FOLDER"], filename))


@app.route("/edit_blog/<slug>", methods=["GET", "POST"])
def edit_blog(slug):
    if "email" not in session:
        return redirect("/login")
    db = get_db()

    blog = db.execute("SELECT * FROM blogs WHERE slug = ?", (slug,)).fetchone()
    if blog is None:
        return "Blog not found", 404
    categories = db.execute("SELECT * FROM categories").fetchall()
    tags = db.execute("SELECT * FROM tags").fetchall()
    selected_tags = [
        row["tag_id"]
        for row in db.execute(
            "SELECT tag_id FROM blog_tags WHERE blog_id = ?", (blog["id"],)
        ).fetchall()
    ]

    if request.method == "POST":
        title = request.form["title"]
        new_slug = slugify(title)  # Update slug if title changes
        content = request.form["content"]
        category_id = request.form["category"]
        new_tags = request.form.getlist("tags")

        image_filename = blog["image_filename"]
        if "image" in request.files:
            image = request.files["image"]
            if image and image.filename != "":
                filename = secure_filename(image.filename)
                image.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                image_filename = filename

        if blog and blog["email"] == session["email"]:
            db.execute(
                "UPDATE blogs SET title = ?, slug = ?, content = ?, image_filename = ?, category_id = ? WHERE slug = ?",
                (title, new_slug, content, image_filename, category_id, slug),
            )
            db.execute("DELETE FROM blog_tags WHERE blog_id = ?", (blog["id"],))
            for tag_id in new_tags:
                db.execute(
                    "INSERT INTO blog_tags (blog_id, tag_id) VALUES (?, ?)",
                    (blog["id"], tag_id),
                )
            db.commit()
        return redirect(f"/blog/{new_slug}")

    return render_template(
        "edit_blog.html",
        blog=blog,
        categories=categories,
        tags=tags,
        selected_tags=selected_tags,
    )


@app.route("/blog/<slug>")
def blog_details(slug):
    db = get_db()
    blog = db.execute(
        """
        SELECT blogs.*, categories.name as category_name 
        FROM blogs 
        LEFT JOIN categories ON blogs.category_id = categories.id 
        WHERE blogs.slug = ?
        """,
        (slug,),
    ).fetchone()

    if not blog:
        return redirect("/homepage")

    tags = [
        row["name"]
        for row in db.execute(
            """
            SELECT tags.name FROM tags 
            INNER JOIN blog_tags ON tags.id = blog_tags.tag_id 
            WHERE blog_tags.blog_id = ?
            """,
            (blog["id"],),
        ).fetchall()
    ]

    return render_template("blog_details.html", blog=blog, tags=tags)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]

        hashed_password = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        db = get_db()
        try:
            db.execute(
                "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
                (name, email, hashed_password),
            )
            db.commit()
            return redirect("/login")
        except sqlite3.IntegrityError:
            return render_template("register.html", error="Email already exists!")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if user and bcrypt.checkpw(
            password.encode("utf-8"), user["password"].encode("utf-8")
        ):
            session["email"] = user["email"]
            session["name"] = user["name"]
            return redirect("/homepage")
        else:
            return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "email" in session:
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE email = ?", (session["email"],)
        ).fetchone()
        return render_template("dashboard.html", user=user)

    return redirect("/login")


@app.route("/create_blog", methods=["GET", "POST"])
def create_blog():
    if "email" not in session:
        return redirect("/login")

    db = get_db()
    categories = db.execute("SELECT * FROM categories").fetchall()
    tags = db.execute("SELECT * FROM tags").fetchall()

    if request.method == "POST":
        title = request.form["title"]
        slug = slugify(title)  # Generate a unique slug
        content = request.form["content"]
        author = session["name"]
        email = session["email"]
        category_id = request.form["category"]
        selected_tags = request.form.getlist("tags")

        image_filename = None
        if "image" in request.files:
            image = request.files["image"]
            if image and image.filename != "":
                filename = secure_filename(image.filename)
                image.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                image_filename = filename

        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO blogs (title, slug, content, author, email, image_filename, category_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title, slug, content, author, email, image_filename, category_id),
        )
        blog_id = cursor.lastrowid  # Get the new blog's ID

        for tag_id in selected_tags:
            cursor.execute(
                "INSERT INTO blog_tags (blog_id, tag_id) VALUES (?, ?)",
                (blog_id, tag_id),
            )

        db.commit()
        return redirect(f"/blog/{slug}")  # Redirect using slug

    return render_template("create_blog.html", categories=categories, tags=tags)


@app.route("/homepage")
def homepage():
    if "email" in session:
        db = get_db()
        blogs = db.execute("SELECT * FROM blogs ORDER BY id DESC").fetchall()
    return render_template("homepage.html", blogs=blogs)


@app.route("/delete_blog/<slug>", methods=["POST"])
def delete_blog(slug):
    if "email" not in session:
        return redirect("/login")

    db = get_db()
    blog = db.execute("SELECT * FROM blogs WHERE slug = ?", (slug,)).fetchone()

    if blog and blog["email"] == session["email"]:
        db.execute("DELETE FROM blogs WHERE slug = ?", (slug,))
        db.commit()

    return redirect("/homepage")


@app.route("/my_blogs")
def my_blogs():
    if "email" not in session:
        return redirect("/login")

    db = get_db()
    user_blogs = db.execute(
        "SELECT * FROM blogs WHERE author = ?", (session["name"],)
    ).fetchall()

    return render_template("user_blog.html", blogs=user_blogs)


@app.route("/logout")
def logout():
    session.pop("email", None)
    return redirect("/login")


# run_with_ngrok(app)
if __name__ == "__main__":
    app.run(debug=True)
