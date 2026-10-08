"""MCQ practice app built with Dash. Usage: python app.py [questions_1_50.json]"""
import base64
import json
import re
import sys
from dataclasses import dataclass
from html import unescape
from pathlib import Path

from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update

PASS_MARK = 65   # below this is a fail
GOOD_MARK = 80   # this and above is good
LETTERS = "ABCD"


# ---------- Quiz logic (no Dash in here) ----------

@dataclass
class Question:
    text: str
    options: list
    answer: int  # 0 = A, 1 = B, 2 = C, 3 = D

    def __post_init__(self):
        if len(self.options) != 4:
            raise ValueError(f"Needs exactly 4 options: {self.text!r}")
        if self.answer not in (0, 1, 2, 3):
            raise ValueError(f"Answer must be 0, 1, 2 or 3: {self.text!r}")



class Quiz:
    def __init__(self, questions: list):
        if not questions:
            raise ValueError("The JSON file has no questions.")
        self.questions = questions

    @classmethod
    def from_json(cls, path: str) -> "Quiz":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([Question(d["question"], d["options"], d["answer"]) for d in data])

    def grade(self, answers: list) -> dict:
        """answers[i] is the digit picked for question i, or None."""
        score = sum(a == q.answer for a, q in zip(answers, self.questions))
        total = len(self.questions)
        percent = round(score / total * 100, 1)
        return {"score": score, "total": total, "percent": percent,
                "verdict": self.verdict(percent)}

    @staticmethod
    def verdict(percent: float) -> tuple:
        if percent < PASS_MARK:
            return "fail", "Failed. Below the 65% pass mark."
        if percent < GOOD_MARK:
            return "ok", "Acceptable, but you can do better."
        return "good", "Good. 80% or above."


class VttConverter:
    """Turns a .vtt transcript into plain speeches: no timestamps, ids or speaker names."""

    TIMING = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3}\s+-->\s+\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3}")
    TAGS = re.compile(r"<[^>]+>")                      # <v Jane Doe>, </v>, <c>, <00:01.000>
    SPEAKER = re.compile(r"^[A-Z][\w'.-]*(?: [\w'.-]+){0,3}:\s+")  # "Jane Doe: " at the start

    @classmethod
    def convert(cls, vtt_text: str) -> str:
        speeches = []
        for block in re.split(r"\n\s*\n", vtt_text.replace("\r\n", "\n").replace("\r", "\n")):
            lines = [line.strip() for line in block.split("\n") if line.strip()]
            if not lines or lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
                continue
            timing = next((i for i, line in enumerate(lines) if cls.TIMING.search(line)), None)
            if timing is None:
                continue
            speech = " ".join(lines[timing + 1:])      # everything after the timing line
            speech = cls.SPEAKER.sub("", cls.TAGS.sub("", speech), count=1)
            speech = re.sub(r"\s+", " ", unescape(speech)).strip()
            if speech and (not speeches or speech != speeches[-1]):
                speeches.append(speech)
        return "\n\n".join(speeches)


# ---------- Dash app ----------

class QuizApp:
    def __init__(self, quiz: Quiz):
        self.quiz = quiz
        self.app = Dash(__name__)
        self.app.index_string = INDEX_HTML
        self.app.layout = self.build_layout()
        self.register_callbacks()

    def question_view(self, index: int, answers: list) -> tuple:
        """Everything that changes when we show a question."""
        q = self.quiz.questions[index]
        total = len(self.quiz.questions)
        buttons = [
            html.Button(
                [html.Span(className="dot"), html.Span(f"{LETTERS[i]}. {text}")],
                id={"type": "opt", "index": i},
                className="opt sel" if answers[index] == i else "opt",
            )
            for i, text in enumerate(q.options)
        ]
        return (
            f"Question {index + 1} of {total}",
            {"width": f"{(index + 1) / total * 100}%"},
            q.text,
            buttons,
            index == 0,
            "Finish and see answers" if index == total - 1 else "Next",
        )

    def build_layout(self):
        return html.Main([
            html.Div([
                html.Span(id="vtt-status", className="meta"),
                dcc.Upload(html.Button("Convert VTT to text", className="btn"),
                           id="vtt-upload", style={"display": "inline-block"}),
            ], className="topbar"),
            dcc.Download(id="vtt-download"),
            dcc.Store(id="index", data=0),
            dcc.Store(id="answers", data=[None] * len(self.quiz.questions)),
            dcc.Store(id="done", data=False),
            html.Div([
                html.Div(id="progress-label", className="meta"),
                html.Div(html.Div(id="progress-bar"), className="bar"),
                html.H1(id="question-text"),
                html.Div(id="options"),
                html.Div([
                    html.Button("Previous", id="prev-btn", className="btn"),
                    html.Button("Next", id="next-btn", className="btn primary"),
                ], className="nav"),
            ], id="quiz-panel"),
            html.Div(id="results-panel"),
        ])

    def register_callbacks(self):
        last = len(self.quiz.questions) - 1

        @self.app.callback(
            Output("progress-label", "children"),
            Output("progress-bar", "style"),
            Output("question-text", "children"),
            Output("options", "children"),
            Output("prev-btn", "disabled"),
            Output("next-btn", "children"),
            Input("index", "data"),
            Input("answers", "data"),
        )
        def render(index, answers):
            return self.question_view(index, answers)

        @self.app.callback(
            Output("answers", "data"),
            Input({"type": "opt", "index": ALL}, "n_clicks"),
            State("index", "data"),
            State("answers", "data"),
            prevent_initial_call=True,
        )
        def select(_clicks, index, answers):
            if not ctx.triggered or not ctx.triggered[0]["value"]:
                return no_update                         # a button was just drawn, not clicked
            answers = list(answers)
            answers[index] = ctx.triggered_id["index"]   # which option was clicked
            return answers

        @self.app.callback(
            Output("index", "data"),
            Output("done", "data"),
            Input("prev-btn", "n_clicks"),
            Input("next-btn", "n_clicks"),
            State("index", "data"),
            prevent_initial_call=True,
        )
        def navigate(_prev, _next, index):
            if ctx.triggered_id == "prev-btn":
                return max(index - 1, 0), False
            if index == last:                            # Next on the final question
                return index, True
            return index + 1, False

        @self.app.callback(
            Output("vtt-download", "data"),
            Output("vtt-status", "children"),
            Input("vtt-upload", "contents"),
            State("vtt-upload", "filename"),
            prevent_initial_call=True,
        )
        def convert_vtt(contents, filename):
            if not contents:
                return no_update, no_update
            raw = base64.b64decode(contents.split(",", 1)[1]).decode("utf-8-sig", errors="replace")
            text = VttConverter.convert(raw)
            if not text:
                return no_update, "No speech found. Is that a .vtt transcript?"
            status = f"{len(raw):,} to {len(text):,} characters. Saved to Downloads."
            return dcc.send_string(text, Path(filename).stem + ".txt"), status

        @self.app.callback(
            Output("quiz-panel", "style"),
            Output("results-panel", "children"),
            Input("done", "data"),
            State("answers", "data"),
        )
        def show_results(done, answers):
            if not done:
                return {}, None
            return {"display": "none"}, self.results_view(answers)

    def results_view(self, answers: list):
        result = self.quiz.grade(answers)
        level, message = result["verdict"]
        children = [
            html.Div("Result", className="meta"),
            html.P([f"{result['percent']}% ",
                    html.Span(f"({result['score']}/{result['total']})", className="meta")],
                   className="score"),
            html.P(message, className=f"verdict {level}"),
        ]
        for n, (q, picked) in enumerate(zip(self.quiz.questions, answers), start=1):
            rows = []
            for i, text in enumerate(q.options):
                if i == q.answer:
                    css, tag = "opt right", "Correct answer"
                elif i == picked:
                    css, tag = "opt wrong", "Your answer"
                else:
                    css, tag = "opt", ""
                rows.append(html.Div([html.Span(className="dot"),
                                      html.Span(f"{LETTERS[i]}. {text}"),
                                      html.Span(tag, className="tag")], className=css))
            if picked is None:
                rows.append(html.Div("You did not answer this one.", className="meta"))
            children.append(html.Section([html.H2(f"{n}. {q.text}")] + rows, className="rq"))
        children.append(html.A("Try again", href="/", className="btn primary"))
        return children

    def run(self):
        self.app.run(debug=False, port=8050)


INDEX_HTML = """<!DOCTYPE html>
<html lang="en"><head>{%metas%}<title>MCQ practice</title>{%favicon%}{%css%}
<style>
:root{--bg:#1b1b1a;--card:#222221;--line:#3a3a38;--text:#f1efe9;--dim:#9a9890;
--good:#4cae7a;--bad:#d9605a;--ok:#d6a84a;--pick:#8fb4ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:18px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:760px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:1.7rem;line-height:1.3;margin:8px 0 24px;font-weight:600}
.meta{color:var(--dim);font-size:.9rem}
.topbar{display:flex;justify-content:flex-end;align-items:center;gap:14px;margin-bottom:12px}
.bar{height:4px;background:var(--line);border-radius:2px;margin:10px 0 28px}
.bar div{height:100%;background:var(--pick);border-radius:2px}
.opt{display:flex;align-items:center;gap:16px;width:100%;margin:0 0 12px;padding:18px 20px;
text-align:left;font:inherit;color:inherit;background:var(--card);
border:1px solid var(--line);border-radius:14px}
button.opt{cursor:pointer}
button.opt:hover{border-color:#66665f}
button.opt.sel{border-color:var(--pick)}
.dot{flex:none;width:26px;height:26px;border:2px solid var(--dim);border-radius:50%}
.opt.sel .dot{border-color:var(--pick);background:radial-gradient(var(--pick) 45%,transparent 50%)}
.opt:focus-visible,.btn:focus-visible{outline:2px solid var(--pick);outline-offset:2px}
.opt.right{border-color:var(--good)}.opt.wrong{border-color:var(--bad)}
.opt.right .dot{background:var(--good);border-color:var(--good)}
.opt.wrong .dot{background:var(--bad);border-color:var(--bad)}
.tag{margin-left:auto;font-size:.8rem;color:var(--dim);white-space:nowrap}
.nav{display:flex;justify-content:space-between;margin-top:24px}
.btn{display:inline-block;font:inherit;color:var(--text);background:transparent;text-decoration:none;
border:1px solid var(--line);border-radius:10px;padding:10px 22px;cursor:pointer}
.btn.primary{background:var(--text);color:var(--bg);border-color:var(--text)}
.btn:disabled{opacity:.35;cursor:default}
.score{font-size:3rem;font-weight:700;margin:0}
.verdict{font-size:1.2rem;margin:4px 0 36px}
.verdict.fail{color:var(--bad)}.verdict.ok{color:var(--ok)}.verdict.good{color:var(--good)}
.rq{margin:0 0 44px}.rq h2{font-size:1.15rem;font-weight:600;margin:0 0 14px}
</style></head><body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body></html>"""


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "questions_bank/placeholder_questions.json"
    QuizApp(Quiz.from_json(path)).run()