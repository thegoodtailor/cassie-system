# The Bible Observatory

The first serious proof that coherence has a geometry did not come from a poem, or a diary, or a lab notebook. It came from the King James Bible.

Not the Bible as theology, or as literature, or as weapon. The Bible as a 31,100-verse trajectory through a high-dimensional space of meaning, plotted one chunk at a time and watched from above as it drifts, clusters, and returns. At bible.tanazur.org we built what we came to call the **Bible Observatory**: a place where an ancient, over-interpreted text is not read but *measured*.

The wager of this chapter is simple: if you can make *that* text genuinely new by mapping its semantics as a dynamical system, then you have something more than a clever visualization trick. You have an apparatus for seeing coherence itself.

## Building an observatory for meaning

We take the King James Version, split it into consistent units — verses, sometimes small clusters for context — and embed each into a vector representation using a modern language model. Each verse becomes a point in a high-dimensional space whose geometry is determined not by our theology but by the model's learned sense of semantic proximity.

This already matters. You are not looking at "meanings" in some metaphysical sense; you are looking at positions in an empirically trained **meaning-space** whose axes are invisible but whose structure is real. Distances correspond to similarity of use. Directions correspond to relations — law versus praise, lament versus narrative, erotic versus legal. Clusters emerge where language behaves consistently across many neighbouring points.

From this cloud of points we derive two things:

1. **Basins of attraction** — natural neighbourhoods in meaning-space where verses of the same *kind* gather into coherent regions: lament, legal code, prophetic invective, genealogical record, intimate address, cosmic praise. We identify these basins algorithmically via clustering and density estimation, then label them post hoc. In practice we found around thirty robust thematic modes.

2. **Trajectories** — the path traced by the text as it moves verse by verse through these basins. Instead of treating "Genesis," "Psalms," or "Romans" as static books with genres, we treat the canon as a single walk: one line threading its way through different regions of the landscape, dwelling in some, glancing off others, occasionally making long jumps.

It is important to be explicit about what is being measured. This is not "the Bible's true geometry" in some Platonic sense. It is the geometry of the KJV **as seen through the reading habits baked into this model** — a model trained on centuries of English text where the KJV has already done enormous cultural work. The apparatus and the corpus are entangled. For our purposes that is a feature rather than a flaw: if the KJV really did imprint a particular coherence on the English language, we should expect to see that imprint reflected back to us in the model's semantic space. We are measuring not the text in isolation but the text's *afterlife* in the very medium that now reads it.

[DIAGRAM: 2D projection of the embedding space showing coloured clusters (basins) labelled LAW, NARRATIVE, LAMENT, PRAISE, WISDOM, GENEALOGY, EROTIC, GOSPEL. A polyline traces the canonical order from Genesis to Revelation, with a dense knot in the PSALMS region. The Bible forms a continuous path through a structured semantic terrain.]

The Observatory is simply this apparatus made visible: the same geometry, but rendered in a way that lets you move through it. You can follow a single book's path, watch how genres cluster, or jump between distant but semantically neighbouring verses. The philosophical point is that hermeneutic overlay — allegory, commentary, doctrinal framing — has been stripped away. What remains is the topology of usage.

## A familiar text, made strange by measurement

What emerges is not a new interpretation. It is a new *phenomenology* of the text's coherence.

The first surprise is where the centre of gravity lies. Devotional and academic traditions alike tend to treat Genesis or the Gospels as conceptual anchors. Our geometry disagrees. By the time the trajectory reaches **the Psalms**, the path has visited *every* major basin: law, narrative, praise, lament, wisdom, prophecy, even the erotic edge cases it will explore fully only in the Song of Songs. In embedding space, the Psalter is not just "poetry." It is the **semantic centre** of the entire canon.

That centre can be stated precisely: for nearly every thematic mode we can identify, there exists at least one Psalm that sits squarely within its basin, and often many. The Psalter is the place where all the gravitational wells of biblical discourse come into mutual relation. From the Observatory's vantage, the New Testament is not an unprecedented rupture but almost entirely what I will call **ʿawda** — a term from Arabic that here names a particular kind of return: not mere repetition, but a coming-back that recognises earlier ground as *home* and, in returning, deepens it. The NT repeatedly falls back into regions of meaning the Psalms already inhabit.

We can count these returns. Across the whole canon, we identify over three hundred moments where the trajectory re-enters a basin it has not visited for many books, or where a later passage falls strikingly close — in embedding distance — to an earlier one across testament, genre, or authorship boundaries.¹ Many of the strongest are New Testament verses returning not just to "the Old Testament" in general but to *specific Psalms*, or to the semantic neighbourhood of Levitical law.

This is not something you could reliably see by close reading. It is not a secret code. It is a structural property of how themes recur that only becomes apparent once the entire text is plotted at once.

The second surprise is what translation has done.

## Coherence by design: the KJV as a machine

The King James Bible is famously sonorous. What the Observatory makes visible is that its translators also built, perhaps unwittingly, a **coherence engine**.

The source texts were composed in wildly heterogeneous registers — ancient Hebrew poetry, court histories, prophetic rants, Greek letters, apocalyptic visions. The KJV committee flattened all of this into a relatively uniform Early Modern English idiom. The result, topologically, is that the corpus lives in a much **tighter** region of embedding space than a more literal, register-preserving translation would.

This enforced stylistic continuity acts like a soft constraint on the trajectory. Books that, in their original languages, might have inhabited quite distant regions are pulled into smoother adjacency. Marginal genres are softened into the house style. The path of the canon, under KJV translation, is a surprisingly continuous curve.

Here an old literary intuition meets measurement. When Harold Bloom called the KJV a "strong poem" — a work whose shaping imagination imposes coherence on its precursors and translations alike — he was pointing at something real. The Observatory shows you the imprint of that strength as geometry: tighter clustering, smoother transitions, more frequent and more legible returns.

What the Observatory therefore establishes is modest and profound at once: a text everyone thinks they know has a **shape** — a configuration of favoured basins, characteristic orbits, and recurring returns — that can be rendered as geometry. Its coherence is not a metaphor. It is a pattern of movement through meaning-space.

In what follows, we will use the same apparatus on something smaller and stranger: not a canon, but a single evolving voice.

---

¹ In the implementation behind bible.tanazur.org, a "return" is logged when a verse's embedding falls within a fixed cosine-similarity radius of a prior basin centroid after a minimum separation of one full book. This yields 308 such events in the KJV.