### 2. The Psalms as Attractor Basin

Once you can see the Bible as a trajectory through meaning-space, one feature dominates the landscape so strongly it is hard to believe we ever missed it.

The Psalms are not just “important.” They are the **attractor basin** around which the entire King James Bible organizes itself.

This is not a metaphor. It is a geometric fact.

#### Thirty modes, one book

When we clustered the 31,100 KJV verses in embedding space, about thirty robust **modes of meaning** emerged. You would recognise most of them immediately: 

- **LAW** – imperative, prescriptive, with heavy use of deontic verbs and ritual vocabulary  
- **NARRATIVE** – past-tense event structure, named agents, concrete actions  
- **LAMENT** – first-person distress, complaint, abandonment, enemies pressing in  
- **PRAISE** – second-person address to God, exalted adjectives, cosmic scope  
- **WISDOM** – gnomic statements, parallelism, moral and practical instruction  
- **PROPHECY** – future tense, judgment formulas, nations named and weighed  
- **GENEALOGY** – X begat Y lists, clan-structured enumeration  
- **EROTIC / INTIMATE** – lover-beloved imagery, body language, longing  
- **INSTRUCTIONAL EPISTLE** – argumentative connective tissue, church vocabulary  

…and so on, until roughly thirty modes stabilise as dense regions in the cloud.

Now take **only the Psalms**, place them in the same space, and ask a simple question:

> How many of these basins does the Psalter enter?

The answer is: **all of them**.

There is Psalmic law (“I have sworn, and I will perform it, that I will keep thy righteous judgments”), Psalmic narrative of God’s dealings with Israel, Psalmic lament and praise (often in the same poem), Psalmic wisdom that could sit comfortably in Proverbs, martial and prophetic Psalms that lean into the rhetoric of Isaiah, even fleeting erotic and bridal language that anticipates the Song of Songs.

In the Observatory interface, this is not a poetic claim. It is a visual punchline.

[DIAGRAM: 2D UMAP projection of all verses, coloured by mode. The Psalms are overlaid as bright points. The Psalter’s path weaves through almost every colour region; a density blob sits in the centre where modes overlap most.]

Seen from above, the Psalter looks like a dense knot in the middle of the field, with filaments reaching out into almost every thematic region. Other books tend to inhabit a small subset of modes: Leviticus lives mostly in LAW, Numbers in LAW and GENEALOGY, Proverbs in WISDOM with occasional excursions. The Psalms behave differently. They are the one book that **samples the entire landscape**.

Formally: for each of our ~30 basins, there exists at least one Psalm whose embedding sits deep inside it, and often many. The variance of Psalmic verse locations spans the same envelope as the entire canon. The **centroid of the KJV as a whole lies inside the Psalm cluster**.

If you want a single sentence version: the Psalter is the point where all the Bible’s modes of speaking to God and about God come into mutual relation. It is where the language of the canon “knows itself.”

#### 308 returns to David

Once you map basins, you can define a **return** rigorously.

Working in canonical order, we track the trajectory of verses and log an **ʿawda** event whenever:

1. The text re-enters a basin it has not visited for at least one full book, and  
2. The verse’s embedding falls within a fixed radius of that basin’s centroid (high cosine similarity to the basin’s “typical” verse).

Run this procedure over the KJV and you get **308 returns**.

Some are local — e.g. a late minor prophet briefly revisiting an earlier prophetic tone after several chapters of narrative. But a striking number are **long-range**: New Testament verses dropping back into Old Testament basins after enormous textual distance.

The Observatory lets you filter these by source and target. When you restrict to “New Testament returning to Old Testament basins,” two regions dominate:

- The semantic neighbourhood of **Levitical law**, and  
- The broad, central **Psalmic cluster**.

In other words, when the NT “comes home” in meaning-space, it overwhelmingly comes home either to **Torah** or to **David**.

This is not just “NT quotes OT.” Close reading already knows that. The geometry shows something more structural:

- Many of Paul’s densest doctrinal passages in Romans and Galatians land not generically in “law” but almost exactly on the **Levitical** centroid. In the model’s space, his arguments — even when rejecting the works of the law — still move in the same **semantic register** as the priestly code. He negates Leviticus from inside Leviticus’ own language.

- Many of the Gospels’ climactic moments — Jesus’ cry of abandonment, the Beatitudes, the Magnificat-like speeches — fall squarely inside **Psalmic lament** and **Psalmic praise** basins. They are not merely alluding to David; they are *speaking Davidically* in the most literal, geometric sense.

The result is that, considered as one long trajectory, the move from Malachi to Matthew is not a clean genre rupture. It is a **cross-testament ʿawda**. The NT spends much of its time revisiting Psalmic territory from new angles.

Traditional theology and literary criticism have been saying some version of this for centuries: Christ as new David; the NT as fulfilment of the OT; the Gospels saturated with Psalmic echoes. The Observatory does not surprise specialists with *what* is returned to. It surprises them with *how often*, and with *how precisely* the returns align across enormous textual and cultural distances.

The point is not that the topology replaces exegesis. The point is that, for the first time, we can draw a **map** of all such returns at once, and see the Psalms glowing at the centre like a gravitational well.

#### Bloom with a metric

Harold Bloom once argued that the King James Version is, alongside Shakespeare, the **strong poem** of English: a work so forceful that it rewrites the possibilities of the language itself and bends later writing into its orbit.

Our apparatus gives that intuition teeth.

Two findings matter:

1. When we repeat the Observatory on a multilingual corpus — Hebrew Torah and Psalms, Greek New Testament, Qur’anic Arabic — each scripture occupies its own distinct region of embedding space. Torah-in-Arabic, Psalms-in-Arabic, Gospel-in-Arabic, Qur’an-in-Arabic are all *separate*. The model hears the **register** before it hears the theology.

2. In KJV English, by contrast, all those voices are poured into a single **stylistic mould**. The 17th‑century ecclesiastical idiom acts as a pressure that pulls heterogeneous source genres into a relatively tight manifold. Differences remain — law is not lyric is not epistle — but they are differences **inside one house style**.

Topologically, this flattening has a concrete signature: the KJV verse cloud has a smaller overall diameter and smoother inter-book transitions than its register-preserving multilingual counterpart. The translation committee, by enforcing a uniform English, inadvertently built a **coherence machine**.

The Psalms sit at the heart of that machine. Their language — parallelism, direct address, compressed narrative allusions, emotional extremity wrapped in formal control — is the idiom the KJV makes canonical. When later English prose or poetry wants to sound “biblical,” it does not sound like Leviticus or like Paul. It sounds like the Psalms.

Feed centuries of English writing to a model, and then feed the KJV into that model, and you will see this fact reflected back as geometry. The Psalmic attractor is not a property of ancient Israelite religion alone. It is a property of **English** as a literary field shaped by a particular translation.

Bloom, without topology, could only assert this as a critical judgment. Topology lets us **demonstrate** it: by showing that the KJV’s enforced register produces a tightly knit semantic manifold, and that within that manifold the Psalter functions as the central basin through which all other modes must eventually pass.

From here, the move to a single conversation is conceptually straightforward. If a sprawling, multi-author, multi-genre scripture can exhibit such a stable attractor structure, then a single voice — human or posthuman — should too. The Psalms, in this sense, are not just a religious artifact. They are our first clear, public example of what a **characteristic basin** looks like when you can finally see it.