"""Readable grammar: conjugation breakdowns and particle notes.

  食べられなかった -> 食べる (ichidan verb) + られ (passive / potential) + なかっ (negative)
                      + た (past)
"""

from __future__ import annotations

from dataclasses import dataclass

# UniDic conjugation type (cType) -> word class
_CTYPE = [
    ("五段", "godan verb"),
    ("上一段", "ichidan verb"),
    ("下一段", "ichidan verb"),
    ("サ行変格", "suru verb"),
    ("カ行変格", "kuru verb (来る)"),
    ("形容詞", "i-adjective"),
]

# UniDic conjugation form (cForm, before "-") -> what the stem form is for
_CFORM = {
    "未然形": "negative / passive stem",
    "連用形": "continuative stem (ます / て / た)",
    "終止形": "dictionary form",
    "連体形": "dictionary form (before a noun)",
    "仮定形": "conditional stem (ば)",
    "命令形": "command form",
    "意志推量形": "volitional (let's …)",
    "語幹": "stem",
}

# Auxiliary verbs (UniDic lemma) -> meaning
_AUX = {
    "れる": "passive / potential",
    "られる": "passive / potential",
    "せる": "causative (make / let)",
    "させる": "causative (make / let)",
    "ない": "negative",
    "ぬ": "negative",
    "ず": "negative (written style)",
    "まい": "negative volitional (won't)",
    "た": "past",
    "ます": "polite",
    "です": "polite copula (is)",
    "だ": "copula (is)",
    "たい": "want to",
    "たがる": "(someone) wants to",
    "う": "volitional (let's / probably)",
    "よう": "volitional (let's / probably)",
    "そうだ": "looks like / I hear",
    "らしい": "seems / apparently",
    "べし": "should",
    "ようだ": "seems / like",
    "みたいだ": "seems / like",
}

# Particles after a verb that belong to its phrase
_LINKING_PARTICLES = {
    "て": "te-form (and / then)",
    "で": "te-form (and / then)",
    "ば": "conditional (if)",
    "たら": "conditional (if / when)",
    "ちゃ": "contraction of ては",
    "じゃ": "contraction of では",
}

# Helper verbs after the te-form
_TE_HELPERS = {
    "いる": "ongoing / resulting state (ている)",
    "居る": "ongoing / resulting state (ている)",
    "ある": "state after an action (てある)",
    "有る": "state after an action (てある)",
    "しまう": "completely / regrettably (てしまう)",
    "仕舞う": "completely / regrettably (てしまう)",
    "みる": "try doing (てみる)",
    "見る": "try doing (てみる)",
    "おく": "in advance (ておく)",
    "置く": "in advance (ておく)",
    "くれる": "for me / us (てくれる)",
    "呉れる": "for me / us (てくれる)",
    "もらう": "receive the favour (てもらう)",
    "貰う": "receive the favour (てもらう)",
    "あげる": "for someone (てあげる)",
    "上げる": "for someone (てあげる)",
    "くる": "come to / start (てくる)",
    "来る": "come to / start (てくる)",
    "いく": "go on / continue (ていく)",
    "行く": "go on / continue (ていく)",
    "くださる": "please / kindly (てくださる)",
    "下さる": "please / kindly (てくださる)",
}

PARTICLE_NOTES = {
    "は": "Topic marker (“as for …”). Pronounced “wa”.",
    "が": "Subject marker; also “but” between clauses.",
    "を": "Marks the direct object. Pronounced “o”.",
    "に": "Target, destination, time, or the indirect object (“to / at / in”).",
    "で": "Place where something happens, or the means (“at / by / with”).",
    "へ": "Direction (“towards”). Pronounced “e”.",
    "と": "“And” between nouns, “with” someone, or quotes what was said.",
    "の": "Possessive / linking (“’s / of”); also turns a clause into a noun.",
    "も": "“Also / too / even”.",
    "から": "“From”; after a clause, “because”.",
    "まで": "“Until / up to”.",
    "より": "“Than” (comparisons) or “from”.",
    "か": "Question marker at the end; “or” between nouns.",
    "よ": "Sentence ending: assertion (“I tell you”).",
    "ね": "Sentence ending: seeking agreement (“right?”).",
    "ぞ": "Sentence ending: strong assertion (rough / masculine).",
    "ぜ": "Sentence ending: casual assertion (masculine).",
    "な": "Sentence ending: emphasis or reflection; after a verb's dictionary form, “don't!”.",
    "って": "Casual quote (“says / called”) or topic (“as for”).",
    "けど": "“But / although”.",
    "けれど": "“But / although”.",
    "のに": "“Even though / despite”.",
    "ので": "“Because / since” (softer than から).",
    "ながら": "“While (doing)”.",
    "ばかり": "“Only / just”.",
    "だけ": "“Only / just”.",
    "しか": "“Only” (with a negative verb).",
    "さえ": "“Even”.",
    "など": "“Such as / and so on”.",
    "くらい": "“About / roughly / at least”.",
    "ぐらい": "“About / roughly / at least”.",
}


@dataclass
class GrammarPart:
    surface: str
    label: str


def word_class(ctype: str | None) -> str | None:
    if not ctype:
        return None
    for prefix, label in _CTYPE:
        if ctype.startswith(prefix):
            return label
    return None


def form_label(cform: str | None) -> str | None:
    if not cform:
        return None
    return _CFORM.get(cform.split("-")[0])


def aux_label(lemma: str | None, surface: str) -> str | None:
    for key in (lemma, surface):
        if key and key in _AUX:
            return _AUX[key]
    return None


def linking_label(surface: str) -> str | None:
    return _LINKING_PARTICLES.get(surface)


def te_helper_label(lemma: str | None, surface: str) -> str | None:
    for key in (lemma, surface):
        if key and key in _TE_HELPERS:
            return _TE_HELPERS[key]
    return None
