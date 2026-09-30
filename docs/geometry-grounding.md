# Geometry grounding

Vision identifies engineering intent and a visual region; it does not identify an Abaqus entity by numeric index.

The grounding layer combines image coordinates, viewport/projection metadata, Abaqus geometry descriptors, and visual/topological evidence. It returns ranked candidates and an explicit confirmation requirement.

The current implementation intentionally stops before real image-to-viewport matching. The next step is a real Abaqus adapter that captures the active viewport camera/projection and geometry descriptors. Only then should screen-space matching be enabled.

## Non-goals

- guessing Face/Edge indices from pixels alone;
- modifying the model during candidate generation;
- treating an LLM confidence value as geometry evidence;
- assuming every uploaded image is an Abaqus viewport screenshot.
