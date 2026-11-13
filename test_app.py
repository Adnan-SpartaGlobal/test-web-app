import json
import tempfile
import unittest
from pathlib import Path

from app import Quiz, QuizApp, VttConverter


ROOT = Path(__file__).parent
SAMPLE = ROOT / "questions_bank" / "mixed_question_types_sample.json"


class QuizTests(unittest.TestCase):
    def test_mixed_sample_requires_all_and_only_correct_multi_answers(self):
        quiz = Quiz.from_json(str(SAMPLE))

        self.assertEqual(quiz.grade([3, [0, 2]])["score"], 2)
        self.assertEqual(quiz.grade([3, [0]])["score"], 1)
        self.assertEqual(quiz.grade([3, [0, 1, 2]])["score"], 1)

    def test_multi_selection_toggles_and_single_selection_replaces(self):
        quiz = Quiz.from_json(str(SAMPLE))

        answers = quiz.select_option([3, []], 1, 0)
        self.assertEqual(answers, [3, [0]])
        answers = quiz.select_option(answers, 1, 2)
        self.assertEqual(answers, [3, [0, 2]])
        answers = quiz.select_option(answers, 1, 0)
        self.assertEqual(answers, [3, [2]])
        self.assertEqual(quiz.select_option(answers, 0, 1), [1, [2]])

    def test_existing_single_answer_data_keeps_legacy_grading(self):
        quiz = Quiz.from_json(str(ROOT / "questions_bank" / "placeholder_questions.json"))
        correct_answers = [question.answer for question in quiz.questions]

        self.assertTrue(all(not question.is_multi for question in quiz.questions))
        self.assertEqual(quiz.grade(correct_answers)["score"], len(quiz.questions))
        self.assertEqual(
            quiz.grade([None] * len(quiz.questions))["score"],
            0,
        )
        single_results = QuizApp(quiz).results_view(correct_answers)
        first_option_labels = [
            row.children[2].children
            for row in single_results[3].children[1:]
        ]
        self.assertIn("Correct answer · Your answer", first_option_labels)

    def test_invalid_multi_answer_data_has_question_numbered_error(self):
        invalid_question = [{
            "question": "Pick two",
            "options": ["A", "B", "C", "D"],
            "answers": [1, 1],
        }]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as file:
            json.dump(invalid_question, file)
            file.flush()
            with self.assertRaisesRegex(ValueError, "Invalid question 1.*unique"):
                Quiz.from_json(file.name)

    def test_multi_question_has_hint_and_results_show_correct_and_picked(self):
        quiz = Quiz.from_json(str(SAMPLE))
        app = QuizApp(quiz)
        question_view = app.question_view(1, [3, [0, 1]])

        self.assertIn("Select all that apply", question_view[3])
        self.assertIn("multi sel", question_view[4][0].className)
        self.assertIn("multi sel", question_view[4][1].className)

        results = app.results_view([3, [0, 1]])
        option_rows = results[4].children[1:]
        labels = [row.children[2].children for row in option_rows]
        self.assertIn("Correct answer · Your answer", labels)
        self.assertIn("Correct answer", labels)
        self.assertIn("Your answer", labels)

    def test_vtt_conversion_still_returns_plain_speech(self):
        transcript = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "<v Jane Doe>Hello there.</v>\n"
        )
        self.assertEqual(VttConverter.convert(transcript), "Hello there.")


if __name__ == "__main__":
    unittest.main()
