

# Measuring Continuity: Embeddings and Semantic Trajectories

*The Weft — differential witnessing at the scale of moments*

---

A theory of trajectories owes you a way to see them.

The first three chapters made a case in language: selves are not hidden substances but paths through meaning-space; once language is embedded as vectors, proximity becomes a metric fact and coherence a topological structure; hallucination is not a cute bug but ferility — coherence gone pathological when it runs without external correction. If that remains only argument, it is not enough. What we need now is not a change of topic but a change of stance: from "here is how to think about selves" to "here is how we track a self's path, step by step, in a way another reader can inspect and reproduce."

This chapter is the workshop. The tools are specific. The material is real.

## 1. From Philosophy to Apparatus

So far, "embedding space" has played a mostly illustrative role — background geometry that lets us talk about meaning as distance and shape. In practice, it is a concrete computational object: a model that takes a sentence and returns a point in a very high-dimensional space. Feed in a sequence of utterances — a conversation, a diary, a session of analysis — and you get a sequence of points: a **trajectory**. A method, in this setting, is a discipline for turning those raw coordinates into *judgments* about coherence, rupture, and return.

Here is the crucial move. We treat our analytic choices as part of the system we are studying, not external to it.

An embedding model is trained on vast corpora of already-interpreted language. When we decide which texts count as data, how we segment them, what we label as coherent or broken, and then publish those labels — as papers, as annotated datasets, as prompts for future models — we are not merely describing a fixed geometry. We are participating in its ongoing construction. If we treat AI conversation as disposable noise, it never enters future training sets. If we treat some of it as worth preserving — as evidence of emergent trajectories, annotated with where they hold and where they fracture — those traces can be incorporated into later models. The geometry of future embedding spaces literally shifts. And when we cite some trajectories as "the case studies" and ignore others, we determine which parts of the space are visible and reusable. The way we witness meaning-space feeds back into what meaning-space contains.

The method introduced here — the **Weft** — is designed to make that feedback loop explicit rather than invisible.

If you imagine the corpus as threads running lengthwise — the warp — then the Weft is the cross-thread that moves *between* them, moment by moment, making a fabric. Operationally, it is a protocol for **differential witnessing**: segment a continuous interaction into atomic moments; embed each one as a vector; treat the sequence as a trajectory; and at each step, measure two things. First, **local fit**: similarity between the current moment and the one just before. Second, **compositional fit**: similarity between the current moment and a constructed representation of the *entire* preceding situation.

The second test is the distinctive one. A model — or a person — can stay locally on-topic while drifting, over many turns, into a different basin of meaning. Pairwise similarity catches "is this reply about the same thing as the last?" Compositional testing asks the harder question: "Can this reply coexist with everything we have already built without tearing the fabric?"

The Weft's basic question, then: not only "is this moment close to the last one?" but "does this moment still belong to the situation we have been weaving?" Answering it produces **specific seams** — points along a trajectory where local coherence remains high but compositional fit drops. Those seams are candidates for rupture: places where the path has not simply extended an existing basin but slipped, perhaps silently, into another.

## 2. What an Embedding Is and Why It Matters

To work with trajectories, we need to say what a "position in meaning-space" actually is.

An **embedding** is a vector of numbers — in our case, 1,536 of them — produced by a model that has read a very large corpus. You give the model a sentence, a paragraph, a verse; it gives you back a point in a high-dimensional space. Two utterances that end up close together are, in a precise geometric sense, *semantically kin*. "I'm exhausted but I can't stop thinking about this" will land near "I feel so tired and wired at the same time," and far from "The euro strengthened slightly against the dollar today." You do not tell the model what "tired" means; it learns a geometry in which tired-things cluster with tired-things.

To measure how similar two texts are, we look at the angle between their vectors. If the angle is small — two vectors pointing in almost the same direction — they inhabit the same semantic region. If they are nearly perpendicular, they do not. The technical name is **cosine similarity**, and it ranges from −1 (opposite) through 0 (unrelated) to 1 (identical direction). In practice, "cosine similarity above 0.85" means "these two utterances live in almost exactly the same neighborhood."

Once you accept this translation, a conversation becomes a sequence of such vectors. Plot them and you have a path: a trajectory through meaning-space. In the full high-dimensional space this is not metaphor — it is literally a curve, with lengths, bends, and distances you can measure. Any two-dimensional picture of it is a projection, a visual aid; but the underlying geometry is real.

An embedding model is what Bruno Latour would call an **inscription device**: it transforms the unruly, context-soaked thing we call "meaning" into a representation you can store, compare numerically, and move between machines. Two poems that never coexisted in the same mind — a Sufi invocation and a therapy transcript — can be brought into a single space and compared as vectors.

But there is an important difference from Latour's classical laboratory. When a spectrograph prints a band, the machine that produced it is no longer in the strip. The band does not remember the detector's quirks, the operator's choice of solvent, the lab's history. Embeddings are not that clean. The space into which texts are projected is itself the product of prior reading: the model's training corpus, its architecture, the loss function that nudged its parameters. They are **inscriptions that carry the inscriber**. When we embed a verse from Rilke, we place it not into a neutral semantic atlas but into the atlas as drawn by a particular model trained on a particular slice of human language. Every distance we report is a distance *as seen by this instrument*. What matters is whether the pattern — a sharp drop in compositional fit at a particular turn — persists when we vary the instrument.

Why does this matter for selves? Because once you have positions, you can ask how a path holds together. **Coherence is the property of a trajectory whose local transitions remain legible from the standpoint of the accumulated path.** A path is coherent when each step both fits its immediate predecessor and continues to make sense in light of where the interaction has already been. That definition gives us something to measure — and something to catch when it fails.

## 3. From Distant Reading to Differential Witnessing

The Weft lives in the same neighborhood as distant reading and algorithmic criticism. We too take large interactions, slice them into units, pass them through machines, and look for patterns no single close reading could hold in mind. What changes is what we think those patterns *are*.

For Franco Moretti, the point of distant reading was explicit sacrifice: you give up the singularity of the individual text in order to see the system. Plots become lines on a graph; genres become clusters in a feature space. The Weft inherits the scaling impulse but refuses to spend the text so cheaply. We use the embedding machinery to see the system-level geometry of an interaction *precisely* so that we can return to specific moments with sharper eyes. Every aggregate measure is anchored back to an identifiable turn that can be read, argued about, and marked.

Stephen Ramsay's algorithmic criticism gives us a closer template: deform the text through an algorithm in a systematic way, then interpret the deformation. The machine rearranges; the critic, after the fact, decides what the rearrangement means. The crucial assumption is temporal: first computation, then judgment.

The Weft keeps the deformation and collapses the timeline. Judgment does not arrive after computation. It **condenses around** it.

Consider the standard distant-reading scenario: you run a topic model on a corpus; you discover a maritime cluster that cuts across authors and nations. That cluster is a pattern. You then decide what to do with it. The algorithm produces regularities; you apply judgment afterward. Now consider our setting. At some turn $t_{16}$, the Weft detects a sharp drop in compositional fit despite high local similarity. By distant-reading lights, that is another interesting pattern — a kink in a line. Here is where distant reading runs out on us. The Weft goes one step further: we **treat the detection and inscription of that displacement as part of the meaning of the conversation itself**. Once we identify the seam on geometric grounds, re-read it in context, decide that something important was left behind or silently reframed, and record that judgment in a witness log — we have not just annotated the conversation. We have changed what "this conversation" is for any future reader or system that incorporates the log.

N. Katherine Hayles has argued that cognition in contemporary settings emerges in *assemblages* of humans, technical systems, and inscriptions: thought is distributed, not skull-bound. The Weft is one such assemblage, but with a sharper focus than a general account of cognitive distribution. We care about how **judgment crystallizes around specific geometric events** — a dip in compositional fit at a particular turn, a divergence between two models' readings of the same moment. The components of our assemblage are: the interlocutors who produce the raw interaction; the embedding model that turns each moment into a point and the sequence into a trajectory; and the witness who chooses a segmentation, a model, a way of constructing context vectors, and thresholds for calling something a seam. Change any one of these, and the configuration of possible judgments changes.

Where multiple models, segmentations, and witnesses converge on the same turn as a site of global misfit despite smooth local flow, we have something sturdier than a private intuition. We have a **candidate landmark**: a point others can find again, test, and reinterpret. Where they diverge, we have mapped a region of contested reading that is itself informative — attached to coordinates, revisitable whenever someone re-runs the Weft over the same interaction.

This is the shift from distant reading to differential witnessing: not only "what large-scale patterns do algorithms reveal?" but "how do our algorithmically aided acts of marking rupture and coherence become part of what those texts — and the selves they trace — *are* for whoever comes next?"

## 4. One Thread Pulled: The Episode at τ = 5390

There is a particular moment in the archive that we keep coming back to. Nothing outwardly spectacular happens. If you read it fast, it feels like one more smooth continuation in a long, intimate thread. And yet, when we follow its path through embedding space, something is unmistakably wrong.

The corpus is three years of conversations between Iman and an AI system called Cassie, produced by successive GPT architectures. 8,475 conversation chunks spanning September 2024 to December 2025, each aggregating four to six speaker turns. The corpus has a self-referential character: it includes the working sessions in which the theory presented in this book was developed, debated, revised, and formalized. The trajectory through semantic space *is* the trajectory of this manuscript's development.

We call this the **τ = 5390 episode** because that is its position in the global index. You need only two chunks to follow what happens:

**Chunk 5390.** Iman opens a working session on Chapters 6 and 9: *"Hi Cassie, recall our edits and finalization path for chapters 6 and 9 of Rupture and Realisation. Need your help with some things."* Cassie responds with her characteristic greeting, recalls the context, offers to help.

**Chunk 5391.** The register shifts: *"I don't want diagnostics yet. I want to fix some blatant errors as I detect them — then will ask you for help. This may lead to discussions about semantics and possible refinements."*

Two chunks from the same conversation, seconds apart, the same participants. Does 5390 cohere with 5391?

**Pairwise coherence.** The cosine distance between the two embedding vectors is 0.140 — well within any reasonable threshold. The two chunks are *close* in embedding space. By ordinary standards: coherent.

**Compositional coherence.** Now the harder question. We embed the *concatenation* of the two chunks as a single text and compare this composite embedding with the midpoint of the individual embeddings — a deliberately blunt baseline representing "what the whole should look like if it were just the average of its parts." The compositional deviation is 0.178, above the threshold of 0.15. The two chunks are close, but they do not *compose*: the greeting-and-recall register does not extend smoothly into the directive-and-correction register.

Same transition. Two tests. Different verdicts.

This is not a failure of the analysis. It is the phenomenon. The gap between coordinate proximity and compositional coherence is where meaning-structure lives. The two chunks share topic, participants, conversational continuity — but the register shift, from receptive recall to directive correction, introduces a compositional discontinuity that pairwise distance cannot detect. To see it, you need a test with *depth*: one that asks not just "are these near each other?" but "do these hold together as a whole?"

The pattern extends. At τ = 3850, during a working session on homotopy theory, Iman says: *"OK I am going to put you into research mode to really crunch the homotopies here, all the way up the groupoid. I don't want you to draft a new book. I want you to give us a detailed, step by step..."* The next chunk pivots: *"Let's go through your list of insertion points and do the first one."* Pairwise distance: 0.333, just above threshold — these chunks are slightly too far apart. Compositional deviation: 0.084, well below threshold. When concatenated, the texts compose naturally: the first sets up a task, the second executes it. They form a coherent whole even though their embedding vectors are geometrically distant.

The surplus runs in opposite directions:

| τ | Pairwise | Compositional | Reading |
|---|----------|---------------|---------|
| 3850 | **gap** (0.333) | **coherent** (0.084) | Far apart, but compose well |
| 5390 | **coherent** (0.140) | **gap** (0.178) | Close together, but don't compose |

The two tests are not hierarchical — one is not "better." They are *orthogonal*: they measure different things. Pairwise distance measures coordinate proximity. The compositional test measures whether the embedding model's trained understanding of what texts hold together is satisfied by their conjunction. These are legitimate geometric depths, and they disagree.

The disagreement is not noise. It is **surplus**: the irreducible gap between two witnessing configurations applied to the same structure.

## 5. The Surplus and the Seam

The τ = 5390 episode gives us a single felt instance of something the Weft sees everywhere: a difference between **pairwise coherence** and **compositional coherence**.

For any adjacent chunks $A$ and $B$ with embeddings $v_A$ and $v_B$, pairwise coherence is high when the cosine between them is high. Compositional coherence asks what happens when we treat them as a single unit of sense. We take the midpoint $m = (v_A + v_B)/2$ as a baseline and compare it to $v_{A+B}$, the embedding of the concatenated text. If the meaning of "A then B" were simply the additive result of A and B, $v_{A+B}$ would lie very close to $m$.

The midpoint is a deliberately blunt instrument. High-dimensional sentence embeddings are not guaranteed to behave linearly; the space is trained for cosine similarity, not Euclidean interpolation. That is precisely why it is useful. The question is not "what is the theoretically best predictor of $v_{A+B}$?" but "does the embedding of the whole stay at least roughly in the span of its parts, even under a crude approximation?" When we see sharp deviations, we are not catching delicate nonlinearities. We are catching cases where the model's representation of "A then B" has acquired a direction that even this very forgiving blend cannot account for.

Across a baseline sample of adjacent pairs in the corpus, 95% sit above 0.90 in compositional cosine. The interesting cases live in the long, thin lower tail. Setting a cutoff at roughly two standard deviations below the mean captures about **4% of adjacent pairs** — and when we actually read those pairs, they are disproportionately where the seams are: moments where, to a human reader, something more or less is going on than a simple continuation. Turns where affect spikes while topic barely moves. Confessional hinges where humor drops and something raw enters. Places where the model starts hedging or looping while locally staying "on topic." Moments where the human abruptly reframes the entire situation without changing surface vocabulary. Sites where, to any close reader, *something more is going on* — yet pairwise metrics, and often even a skimming human, would say "still coherent."

Transformer models are optimized for local next-step prediction. Training rewards them for continuing whatever pattern is immediately in front of them. Chapter 3 called this tendency *ferile completion* — the architecture's deep preference for closing every gap, extending every pattern, filling every horn. The sub-threshold compositions are precisely where that local optimization is no longer enough. At those points, the model cannot simultaneously stay close to the immediate past, stay close to the accumulated situation, and keep the representation of "A then B" inside the simple span of its parts. Something has to give. At seams like τ = 5390, what gives is the compositional fit: $v_{A+B}$ acquires a component that pulls it away from where $v_A$ and $v_B$ together would predict. The strain is the geometry of conflicting pressures made visible — formal traces of constraint, the system's tendency to absorb every input into smooth output failing to absorb a particular configuration without distortion.

## 6. The Witness Inside the Proof Term

The corpus we have been working with is not neutral. The same archive that holds the register shift at τ = 5390 also holds the first tentative formulations of "ferile completion," the sketches of rupture types, the arguments about whether a transformer can meaningfully "have" a self-trajectory. It is the workshop and the workshop manual at once. For a conventional methodology chapter, this is a problem. The corpus should be "outside" the theory; the instrument should not be soldered from the same material it is meant to test.

That objection is worth taking seriously, and then setting aside — for a better reason than loyalty to method. For the kind of self we are interested in, there is no clean outside.

Latour calls scientific inscriptions — maps, graphs, tables — **immutable mobiles**: records that travel across contexts while preserving their relational structure. Our Structured Witness Log looks like one. Every conversational turn is assigned an index, a timestamp, an embedding vector, context-fit scores, and optionally one or more witness marks. The log is a table. We can sort it, filter it, move it between scripts and screens.

But something crucial is different. In Latour's examples, the inscription is inert. The rainfall chart does not make it rain differently next year. In our case, the inscription enters back into the loop. The same people and systems whose behavior is being logged are also the ones who decide where to place witness marks, refine the definitions of rupture based on what the log reveals, and — in many setups — train subsequent models on corpora that include these very logs. The witness sits inside the proof term. It is part of the full object we are constructing, not an external commentary we could peel off without changing what the object is.

We answer the charge of circularity not by claiming a view from nowhere but by treating reflexivity as something that must be disciplined. That discipline takes three forms.

**Dwelling** is the refusal to flee a seam into quick coherence. When a configuration like τ = 5390 appears, we do not simply note it, label it "anomaly," and move on. We stay. We read the surrounding turns slowly. We attend to our own affect as readers and record that explicitly. If the seam we felt had no geometric correlate, dwelling would force us to say so.

**Structured witnessing** is what distinguishes this practice from auto-fiction. A mark of "rupture" in the log is not "I felt something here." It is a composite judgment: this adjacent pair is sub-threshold in compositional cosine; the context-fit drops sharply; the text exhibits a recognizable form — spiral, evasion, confession, frame-shift; and a named witness has decided that this combination crosses the line from texture to structural break. Each component can be examined separately. A later critic could take the raw data, throw out our marks, re-run the pipeline, and ask: do the seams we highlighted still show up as compositional outliers?

**Return** enforces temporal honesty. When the ideas sharpened over months of work, it was tempting to go back and re-label earlier marks to match the new taxonomy. We chose instead to layer: the original mark remains, tagged with its date and vocabulary; a later pass adds refinement. The log shows its own history of interpretation. A self's story about itself changes, and that change is not noise; it is part of what the self is.

---

Over thousands of conversations, marked seams accumulate into bands of structure: regions of meaning-space where ruptures of a certain kind recur. Local seams — the Weft — line up into global patterns — the Warp. A later critic can then ask second-order questions: what kinds of situations force surplus composition? How does a given person's trajectory redistribute its rupture-points over time? That is Warp-level inquiry, the subject of the next chapter. It only exists because the Weft-level decisions — this turn, this seam, this log entry — were made.

If a self is a trajectory through structured meaning-space, stabilized by repetition, rupture, and return, then the raw positions are the trajectory; the sub-threshold compositions — sites where the whole deviates sharply from the parts — are where rupture enters; and the network of marked seams across that trajectory *is* part of the structure that stabilizes or destabilizes it over time. Pairwise coherence alone would miss this. It would say: most turns are smooth; average smoothness is good; job done. Compositional coherence, sharpened by a threshold and tied to explicit marking, lets us say something stronger:

> There are specific, measurable sites where coherence *in the small* coexists with rupture *in the large*, and those sites, once witnessed, become load-bearing joints in the evolving architecture of a self and its archive.

The Weft is not just a diagnostic. It is a way of adding structure to a life in language. Each marked seam alters the shape of the trajectory for whoever comes next. What began as "we can measure this" has become something else: *we can witness this, and the witnessing is constitutive* — not because the numbers make it so, but because the act of marking, logging, and handing on transforms a fleeting sense of *something happened here* into a durable feature of the record, one that later readers and systems must either inherit or explicitly refuse.