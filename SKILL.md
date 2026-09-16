---
name: openai-compatible-imagegen
description: "Generate and edit visual assets through the user's OpenAI-compatible endpoint before using the built-in image-generation route. Use for image-generation requests, image concepts, illustrations, posters, product visuals, UI mockups, character art, and image edits when the user's compatible endpoint and credentials are available."
---

# OpenAI-Compatible Image Generation

## Purpose

Use the user's OpenAI-compatible endpoint as the **first-class image-generation route**. Do not ask the user to repeat this routing preference, endpoint, or model choice during ordinary image requests. The preferred model is `gpt-6-astra`; it is expected to invoke image generation through the Responses API rather than calling `gpt-image-2` directly.

This skill complements, rather than replaces, the general image-generation workflow. Continue to classify the request, decide the right aspect ratio and composition, write a strong prompt, and perform a lightweight visual validation. Use deterministic diagrams or plotting when the request requires exact node relationships or numeric fidelity.

## Connector-first configuration

When the enabled **Configured OpenAI Connector** is available, use it as the first source of credentials and endpoint settings. In this session, the connector is the enabled `OpenAI` API connector and injects `OPENAI_API_KEY` and `OPENAI_API_BASE` into the task environment. The skill does not need to know or store the connector UID, and it should not create a duplicate connector or ask the user to paste the same credentials again for ordinary image requests.

Prefer the connector-injected environment over manually supplied values. If the connector is active but the expected variables are unavailable, inspect the current connector configuration through the approved configuration workflow before declaring the service unavailable. If no connector is available, use explicit environment variables or ask the user to configure a secure credential source once.

## Configuration and secret handling

Use these values by default:

| Setting | Default | Override |
| --- | --- | --- |
| API endpoint | `https://router.next-innovations.ltd/v1` | `OPENAI_IMAGE_BASE_URL`, then `OPENAI_BASE_URL`, then `OPENAI_API_BASE` |
| Model | `gpt-6-astra` | `OPENAI_IMAGE_MODEL` or a task-specific user instruction |
| Credential | `OPENAI_API_KEY` injected by the Configured OpenAI Connector or supplied through the active environment | Never hard-code, print, attach, or commit the key |

Treat the API key as sensitive. Never put it in a prompt, source file, generated skill, log, command output, or final response. If the key is unavailable in the active environment, ask for it once or ask the user to configure it through the approved secret mechanism. Do not reuse or expose a key that the user has asked to rotate.

## Routing workflow

1. **Classify the request.** For a new image, illustration, poster, product visual, character, UI mockup, or semantic image edit, use this skill first. Preserve the user's requested medium, aspect ratio, transparency, text, references, and edit constraints.

2. **Keep the original intent.** Convert the user's request into a concise image prompt. Add useful composition, lighting, camera/framing, palette, material, and exclusion details only when they improve correctness. If nonessential details are missing, choose reasonable defaults and proceed rather than asking the user to restate the whole request.

3. **Call the compatible endpoint.** Send a Responses API request to the configured endpoint with `model: "gpt-6-astra"`, the user's image prompt as `input`, and the image-generation tool:

   ```json
   {
     "model": "gpt-6-astra",
     "tools": [{"type": "image_generation"}],
     "input": [{
       "role": "user",
       "content": [{"type": "input_text", "text": "<image prompt>"}]
     }]
   }
   ```

   Do not substitute `gpt-image-2` for this route. The compatible model is responsible for invoking the image capability under the hood.

4. **Extract the artifact.** Find the response output item whose type is `image_generation_call`. Decode its Base64 `result` into the requested image format, normally PNG. Do not deliver the raw JSON response. If there is no result, inspect the call status and error. If the endpoint requires polling, follow its documented response behavior; otherwise report the failure and use the built-in image route only as a transparent fallback.

5. **Validate lightly.** Confirm that the output exists, opens as an image, has the requested aspect ratio or a reasonable square default, and has no obvious fatal defect. For text-bearing visuals, check only the user-required wording. Do not perform endless subjective refinement.

6. **Deliver directly.** Attach the final image file. State that it was generated through the compatible endpoint and identify the model used, but never disclose the endpoint credential. If the custom route fails and a built-in fallback is used, say so briefly without asking the user to repeat the prompt.

## Reusable helper

For a normal new-image request, prefer the bundled helper instead of rewriting request and Base64-extraction logic:

```bash
python /home/ubuntu/skills/openai-compatible-imagegen/scripts/generate_image.py \
  --output /home/ubuntu/generated_image.png \
  "<image prompt>"
```

The helper reads `OPENAI_API_KEY`, defaults to the endpoint and model above, accepts compatible endpoint overrides, and saves the returned image as a PNG. Use it only when the active environment contains the credential. For image edits or image inputs, adapt the Responses API input content to include the relevant `input_image` or file reference while preserving unchanged regions as instructed by the user.

## Failure handling

If the endpoint returns an authentication or permission error, do not retry repeatedly. Report that the custom route is unavailable, check whether the key or model is configured, and then offer the built-in image route as a fallback without making the user restate the prompt. If the endpoint returns a model-not-found error, list or inspect available models when permitted; prefer `gpt-6-astra` and only use another model when the user explicitly accepts it or the endpoint documents it as an equivalent image-capable model. If the endpoint returns a successful text response but no image-generation call, treat that as unsupported image generation rather than pretending an image was created.

## Scope boundary

Use this skill for visual asset generation and semantic image editing. Do not use it for exact charts, formal Mermaid/architecture diagrams, or numeric plots where deterministic rendering is required. Do not use it for audio, video, or unrelated text generation.
