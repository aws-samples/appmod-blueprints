# Cognito hosted UI — finance-assistant theme

Brands the Cognito hosted sign-in / sign-up / MFA / forgot-password screens
to match the finance-assistant web UI (`examples/finance-assistant/web-ui/`).

## Files

| File | Role |
|---|---|
| `finance-ui.css` | Theme applied via `aws_cognito_user_pool_ui_customization`. Palette pulled from `tailwind.config.ts` (slate/ink + cyan accent + gold). |
| `logo.svg` | Design source for the wordmark. |
| `logo.png` | Generated from `logo.svg`; uploaded to Cognito. Not committed — build locally (see below). |
| `render-logo.sh` | Rasterizes `logo.svg` → `logo.png` using `rsvg-convert` (preferred) or ImageMagick as a fallback. |

## Why CSS is narrow

Cognito hosted UI ignores anything outside its whitelisted
`*-customizable` classes and strips custom fonts via CSP. The CSS here
sticks to that whitelist on purpose — the theme looks like the product
even though Cognito owns the markup.

## Regenerate the logo

```
cd terraform/cognito_ui
./render-logo.sh
```

`rsvg-convert` (`brew install librsvg`) is preferred; the script falls
back to ImageMagick `convert` if rsvg is missing. Output is a 480×128 PNG
well under Cognito's 100KB cap.

## Applying changes

The `aws_cognito_user_pool_ui_customization` resource in
`terraform/cognito_ui.tf` reads both files. After editing CSS or
regenerating the logo:

```
cd terraform
terraform plan -target=aws_cognito_user_pool_ui_customization.finance
terraform apply -target=aws_cognito_user_pool_ui_customization.finance
```

Changes are live on the Cognito hosted UI immediately — no UI deploy needed.
