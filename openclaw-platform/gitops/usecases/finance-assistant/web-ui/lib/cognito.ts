// Cognito direct-auth helpers — called from server API routes so the
// client secret never leaves the pod. Client talks to /api/auth/* only.

import {
  CognitoIdentityProviderClient,
  InitiateAuthCommand,
  RespondToAuthChallengeCommand,
  SignUpCommand,
  ConfirmSignUpCommand,
  ForgotPasswordCommand,
  ConfirmForgotPasswordCommand,
  ResendConfirmationCodeCommand,
} from "@aws-sdk/client-cognito-identity-provider";
import { createHmac } from "crypto";
import {
  CLIENT_ID, CLIENT_SECRET, COGNITO_REGION, verifyIdToken,
} from "./auth";

export const cognito = new CognitoIdentityProviderClient({ region: COGNITO_REGION });

function secretHash(username: string): string {
  if (!CLIENT_SECRET) return "";
  return createHmac("sha256", CLIENT_SECRET).update(username + CLIENT_ID).digest("base64");
}

export type AuthResult =
  | { kind: "ok"; idToken: string; refreshToken?: string; sub: string; email?: string }
  | { kind: "mfa"; session: string; email: string }
  | { kind: "new_password"; session: string; email: string }
  | { kind: "error"; code: string; message: string };

function asError(e: unknown): { kind: "error"; code: string; message: string } {
  const err = e as { name?: string; message?: string };
  // Return the Cognito error code unchanged — the client maps a small
  // set of friendly messages. Unknown codes fall back to a generic.
  const code = err.name || "UnknownError";
  const message = err.message || "Something went wrong. Try again.";
  return { kind: "error", code, message };
}

export async function signIn(email: string, password: string): Promise<AuthResult> {
  try {
    const res = await cognito.send(new InitiateAuthCommand({
      AuthFlow: "USER_PASSWORD_AUTH",
      ClientId: CLIENT_ID,
      AuthParameters: {
        USERNAME: email,
        PASSWORD: password,
        ...(CLIENT_SECRET ? { SECRET_HASH: secretHash(email) } : {}),
      },
    }));

    if (res.ChallengeName === "SOFTWARE_TOKEN_MFA" || res.ChallengeName === "SMS_MFA") {
      return { kind: "mfa", session: res.Session!, email };
    }
    if (res.ChallengeName === "NEW_PASSWORD_REQUIRED") {
      return { kind: "new_password", session: res.Session!, email };
    }
    const idToken = res.AuthenticationResult?.IdToken;
    if (!idToken) return { kind: "error", code: "NoIdToken", message: "Auth succeeded but no id_token returned." };
    const claims = await verifyIdToken(idToken);
    if (!claims) return { kind: "error", code: "IdTokenVerifyFailed", message: "id_token failed verification." };
    return {
      kind: "ok",
      idToken,
      refreshToken: res.AuthenticationResult?.RefreshToken,
      sub: claims.sub, email: claims.email,
    };
  } catch (e) { return asError(e); }
}

export async function respondMfa(email: string, session: string, code: string): Promise<AuthResult> {
  try {
    const res = await cognito.send(new RespondToAuthChallengeCommand({
      ClientId: CLIENT_ID,
      ChallengeName: "SOFTWARE_TOKEN_MFA",
      Session: session,
      ChallengeResponses: {
        USERNAME: email,
        SOFTWARE_TOKEN_MFA_CODE: code,
        ...(CLIENT_SECRET ? { SECRET_HASH: secretHash(email) } : {}),
      },
    }));
    const idToken = res.AuthenticationResult?.IdToken;
    if (!idToken) return { kind: "error", code: "NoIdToken", message: "MFA accepted but no id_token." };
    const claims = await verifyIdToken(idToken);
    if (!claims) return { kind: "error", code: "IdTokenVerifyFailed", message: "id_token failed verification." };
    return {
      kind: "ok",
      idToken,
      refreshToken: res.AuthenticationResult?.RefreshToken,
      sub: claims.sub, email: claims.email,
    };
  } catch (e) { return asError(e); }
}

export async function respondNewPassword(email: string, session: string, newPassword: string): Promise<AuthResult> {
  try {
    const res = await cognito.send(new RespondToAuthChallengeCommand({
      ClientId: CLIENT_ID,
      ChallengeName: "NEW_PASSWORD_REQUIRED",
      Session: session,
      ChallengeResponses: {
        USERNAME: email,
        NEW_PASSWORD: newPassword,
        ...(CLIENT_SECRET ? { SECRET_HASH: secretHash(email) } : {}),
      },
    }));
    const idToken = res.AuthenticationResult?.IdToken;
    if (!idToken) return { kind: "error", code: "NoIdToken", message: "Set password accepted but no id_token." };
    const claims = await verifyIdToken(idToken);
    if (!claims) return { kind: "error", code: "IdTokenVerifyFailed", message: "id_token failed verification." };
    return {
      kind: "ok",
      idToken,
      refreshToken: res.AuthenticationResult?.RefreshToken,
      sub: claims.sub, email: claims.email,
    };
  } catch (e) { return asError(e); }
}

export type SignUpResult =
  | { kind: "ok"; destination?: string }
  | { kind: "error"; code: string; message: string };

export async function signUp(email: string, password: string, name?: string): Promise<SignUpResult> {
  try {
    const res = await cognito.send(new SignUpCommand({
      ClientId: CLIENT_ID,
      Username: email,
      Password: password,
      UserAttributes: [
        { Name: "email", Value: email },
        ...(name ? [{ Name: "name", Value: name }] : []),
      ],
      ...(CLIENT_SECRET ? { SecretHash: secretHash(email) } : {}),
    }));
    return { kind: "ok", destination: res.CodeDeliveryDetails?.Destination };
  } catch (e) { return asError(e) as SignUpResult; }
}

export type SimpleResult = { kind: "ok" } | { kind: "error"; code: string; message: string };

export async function confirmSignUp(email: string, code: string): Promise<SimpleResult> {
  try {
    await cognito.send(new ConfirmSignUpCommand({
      ClientId: CLIENT_ID,
      Username: email,
      ConfirmationCode: code,
      ...(CLIENT_SECRET ? { SecretHash: secretHash(email) } : {}),
    }));
    return { kind: "ok" };
  } catch (e) { return asError(e) as SimpleResult; }
}

export async function resendConfirmation(email: string): Promise<SimpleResult> {
  try {
    await cognito.send(new ResendConfirmationCodeCommand({
      ClientId: CLIENT_ID,
      Username: email,
      ...(CLIENT_SECRET ? { SecretHash: secretHash(email) } : {}),
    }));
    return { kind: "ok" };
  } catch (e) { return asError(e) as SimpleResult; }
}

export async function forgotPassword(email: string): Promise<SimpleResult> {
  try {
    await cognito.send(new ForgotPasswordCommand({
      ClientId: CLIENT_ID,
      Username: email,
      ...(CLIENT_SECRET ? { SecretHash: secretHash(email) } : {}),
    }));
    return { kind: "ok" };
  } catch (e) { return asError(e) as SimpleResult; }
}

export async function confirmForgotPassword(email: string, code: string, newPassword: string): Promise<SimpleResult> {
  try {
    await cognito.send(new ConfirmForgotPasswordCommand({
      ClientId: CLIENT_ID,
      Username: email,
      ConfirmationCode: code,
      Password: newPassword,
      ...(CLIENT_SECRET ? { SecretHash: secretHash(email) } : {}),
    }));
    return { kind: "ok" };
  } catch (e) { return asError(e) as SimpleResult; }
}
