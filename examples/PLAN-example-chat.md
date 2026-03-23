# Project {#project}

## Metadata {#metadata}

    next_id: 125

## Tickets {#tickets}

* ## Ticket: Epic: Authentication and user management {#1}

      status: open
      created: 2026-03-23 05:32:06 UTC
      updated: 2026-03-23 05:32:06 UTC

  User registration, login, profile management, and session handling.

  * ## Ticket: Task: User registration flow {#2}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Email/password registration with verification. Hash passwords with bcrypt, send verification email, handle duplicate detection.

    * ## Ticket: Task: Registration API endpoint {#60}

          status: open
          created: 2026-03-23 05:54:35 UTC
          updated: 2026-03-23 05:54:35 UTC

      Build POST /auth/register accepting email and password. Validate email format and password strength (min 8 chars, mixed case). Return 409 on duplicate email with a generic "account exists" message to prevent enumeration.

    * ## Ticket: Task: Password hashing {#61}

          status: open
          created: 2026-03-23 05:54:35 UTC
          updated: 2026-03-23 05:54:35 UTC

      Hash passwords using bcrypt with a cost factor of 12 before storing. Never log or return plaintext passwords in API responses.

    * ## Ticket: Task: Email verification flow {#62}

          status: open
          created: 2026-03-23 05:54:35 UTC
          updated: 2026-03-23 05:54:35 UTC

      Generate a signed verification token, store it with an expiry (24h), and send a verification email via the transactional email service. On GET /auth/verify?token=X, mark the account as verified and invalidate the token.

  * ## Ticket: Task: Login and session management {#3}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    JWT-based authentication with refresh tokens. Issue short-lived access tokens and long-lived refresh tokens, handle token rotation.

    * ## Ticket: Task: Login endpoint and JWT issuance {#63}

          status: open
          created: 2026-03-23 05:54:41 UTC
          updated: 2026-03-23 05:54:41 UTC

      POST /auth/login validates credentials and returns a short-lived access token (15min) and a long-lived refresh token (7d). Store refresh token hashes server-side to enable revocation.

    * ## Ticket: Task: Token refresh and rotation {#64}

          status: open
          created: 2026-03-23 05:54:41 UTC
          updated: 2026-03-23 05:54:41 UTC

      POST /auth/refresh accepts a refresh token, validates it, issues a new access/refresh pair, and invalidates the old refresh token. This rotation prevents replay attacks if a token is leaked.

    * ## Ticket: Task: Session revocation and multi-device logout {#65}

          status: open
          created: 2026-03-23 05:54:41 UTC
          updated: 2026-03-23 05:54:41 UTC

      Maintain a per-user list of active refresh tokens. Provide endpoints to revoke a single session or all sessions (logout everywhere). Revoked tokens must be rejected immediately.

  * ## Ticket: Task: User profiles {#4}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Display name, avatar upload, status message, online/offline presence indicator.

    * ## Ticket: Task: Profile data model and API {#66}

          status: open
          created: 2026-03-23 05:54:59 UTC
          updated: 2026-03-23 05:54:59 UTC

      CRUD endpoints for display name, bio, and status message. Validate length limits and sanitize HTML/script content.

    * ## Ticket: Task: Avatar upload and processing {#67}

          status: open
          created: 2026-03-23 05:54:59 UTC
          updated: 2026-03-23 05:54:59 UTC

      Accept image uploads, validate format (JPEG/PNG/WebP) and size (max 5MB), resize to standard dimensions (128px, 256px, 512px), and store in object storage. Serve via CDN with cache headers.

    * ## Ticket: Task: Online presence system {#68}

          status: open
          created: 2026-03-23 05:54:59 UTC
          updated: 2026-03-23 05:54:59 UTC

      Track user presence via WebSocket heartbeats. Broadcast online/offline/away status changes to relevant contacts. Use a short TTL (90s) in Redis to auto-expire stale sessions.

  * ## Ticket: Task: Account settings {#5}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Change password, update email, notification preferences, delete account with data export.

    * ## Ticket: Task: Password and email change {#69}

          status: open
          created: 2026-03-23 05:54:59 UTC
          updated: 2026-03-23 05:54:59 UTC

      Require current password confirmation before allowing password change or email update. Email changes should trigger re-verification on the new address before switching.

    * ## Ticket: Task: Account deletion with data export {#70}

          status: open
          created: 2026-03-23 05:54:59 UTC
          updated: 2026-03-23 05:54:59 UTC

      Generate a downloadable ZIP of the user's data (messages, files, profile) per GDPR requirements. After export, soft-delete the account with a 30-day grace period before hard deletion.

* ## Ticket: Epic: Real-time messaging {#6}

      status: open
      created: 2026-03-23 05:32:06 UTC
      updated: 2026-03-23 05:32:06 UTC

  Core 1:1 and group messaging with delivery guarantees.

  * ## Ticket: Task: WebSocket connection layer {#7}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Persistent WebSocket connections with automatic reconnection, heartbeat, and backpressure handling.

    * ## Ticket: Task: WebSocket handshake and authentication {#71}

          status: open
          created: 2026-03-23 05:55:06 UTC
          updated: 2026-03-23 05:55:06 UTC

      Upgrade HTTP connection to WebSocket after validating the JWT in the initial handshake. Reject unauthenticated connections before the upgrade completes.

    * ## Ticket: Task: Heartbeat and reconnection logic {#72}

          status: open
          created: 2026-03-23 05:55:06 UTC
          updated: 2026-03-23 05:55:06 UTC

      Server sends ping frames every 30s; client must respond within 10s or the connection is considered dead. Client-side implements exponential backoff reconnection (1s, 2s, 4s... capped at 30s) with jitter.

    * ## Ticket: Task: Connection state sync on reconnect {#73}

          status: open
          created: 2026-03-23 05:55:06 UTC
          updated: 2026-03-23 05:55:06 UTC

      On reconnection, the client sends its last-seen message timestamp. The server replays any missed events since that timestamp so the client catches up without a full reload.

  * ## Ticket: Task: 1:1 direct messages {#8}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Send and receive text messages between two users. Store message history, handle offline delivery.

    * ## Ticket: Task: Conversation data model {#74}

          status: open
          created: 2026-03-23 05:55:11 UTC
          updated: 2026-03-23 05:55:11 UTC

      Create a conversations table linking two users. Ensure uniqueness (user A + user B = same conversation regardless of order). Store last_message_at for efficient sorting in the conversation list.

    * ## Ticket: Task: Message sending and storage {#75}

          status: open
          created: 2026-03-23 05:55:11 UTC
          updated: 2026-03-23 05:55:11 UTC

      POST endpoint to send a message within a conversation. Persist to the database with sender_id, conversation_id, body, and created_at. Broadcast the message to the recipient via WebSocket in real-time.

    * ## Ticket: Task: Offline message queue and delivery {#76}

          status: open
          created: 2026-03-23 05:55:11 UTC
          updated: 2026-03-23 05:55:11 UTC

      If the recipient is offline, queue the message for delivery. On reconnect, deliver all pending messages in chronological order. Mark them as delivered once the client acknowledges receipt.

  * ## Ticket: Task: Message delivery and read receipts {#9}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Track sent, delivered, and read states per message. Sync receipt status across devices.

    * ## Ticket: Task: Delivery receipt tracking {#77}

          status: open
          created: 2026-03-23 05:55:16 UTC
          updated: 2026-03-23 05:55:16 UTC

      When a message is persisted, mark it as "sent". When the recipient's device receives and acknowledges the message via WebSocket, update status to "delivered". Push the status change back to the sender.

    * ## Ticket: Task: Read receipt tracking {#78}

          status: open
          created: 2026-03-23 05:55:16 UTC
          updated: 2026-03-23 05:55:16 UTC

      When the recipient scrolls a message into view for at least 1 second, fire a read event. Batch read receipts (debounce 2s) to avoid flooding. Update the read watermark per conversation per user.

    * ## Ticket: Task: Multi-device receipt sync {#79}

          status: open
          created: 2026-03-23 05:55:16 UTC
          updated: 2026-03-23 05:55:16 UTC

      Store receipt state server-side so all of a user's devices reflect the same read/unread state. When a message is read on one device, push the updated watermark to all other active sessions.

  * ## Ticket: Task: Typing indicators {#10}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Broadcast typing state over WebSocket. Debounce on sender side, auto-expire on receiver side.

  * ## Ticket: Task: Message editing and deletion {#11}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Edit message content within a time window. Soft-delete with "message deleted" placeholder.

  * ## Ticket: Task: Rich content messages {#12}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Support for links with preview cards, code blocks with syntax highlighting, and markdown formatting.

    * ## Ticket: Task: URL preview cards {#80}

          status: open
          created: 2026-03-23 05:55:20 UTC
          updated: 2026-03-23 05:55:20 UTC

      Detect URLs in message text using regex, fetch metadata (Open Graph title, description, image) server-side via a background job, and cache the preview data. Render inline cards below the message.

    * ## Ticket: Task: Code block rendering {#81}

          status: open
          created: 2026-03-23 05:55:20 UTC
          updated: 2026-03-23 05:55:20 UTC

      Parse markdown fenced code blocks, identify the language tag, and apply syntax highlighting using a library like Prism or Highlight.js. Support copy-to-clipboard on hover.

    * ## Ticket: Task: Markdown formatting {#82}

          status: open
          created: 2026-03-23 05:55:20 UTC
          updated: 2026-03-23 05:55:20 UTC

      Parse a safe subset of markdown (bold, italic, strikethrough, inline code, lists, blockquotes) at render time. Sanitize output to prevent XSS by stripping raw HTML tags and script content.

* ## Ticket: Epic: Group channels {#13}

      status: open
      created: 2026-03-23 05:32:06 UTC
      updated: 2026-03-23 05:32:06 UTC

  Multi-user channels with roles and permissions.

  * ## Ticket: Task: Channel creation and settings {#14}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Create public or private channels. Set name, description, topic. Archive and unarchive channels.

    * ## Ticket: Task: Channel CRUD endpoints {#83}

          status: open
          created: 2026-03-23 05:55:26 UTC
          updated: 2026-03-23 05:55:26 UTC

      POST /channels to create with name, description, and visibility (public/private). PUT /channels/:id for settings updates. Validate name uniqueness within a workspace and enforce character limits.

    * ## Ticket: Task: Channel topic and description {#84}

          status: open
          created: 2026-03-23 05:55:26 UTC
          updated: 2026-03-23 05:55:26 UTC

      Allow admins to set a channel topic (displayed in the header) separate from the longer description. Track topic change history with timestamps and who changed it.

    * ## Ticket: Task: Channel archiving {#85}

          status: open
          created: 2026-03-23 05:55:26 UTC
          updated: 2026-03-23 05:55:26 UTC

      Archived channels become read-only with no new messages allowed. Archive and unarchive endpoints restricted to channel owner or admin. Archived channels are hidden from the default channel list but remain searchable.

  * ## Ticket: Task: Member management {#15}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Invite, remove, and ban members. Role system: owner, admin, member. Transfer ownership.

    * ## Ticket: Task: Invite and join flow {#86}

          status: open
          created: 2026-03-23 05:55:31 UTC
          updated: 2026-03-23 05:55:31 UTC

      Public channels: any user can join directly. Private channels: members with invite permission generate invite links or add users by ID. Invites can have an expiry and usage limit.

    * ## Ticket: Task: Role assignment and ownership transfer {#87}

          status: open
          created: 2026-03-23 05:55:31 UTC
          updated: 2026-03-23 05:55:31 UTC

      Roles stored as an enum on the channel_members join table. Owners can promote members to admin and transfer ownership. Enforce that every channel has exactly one owner at all times.

    * ## Ticket: Task: Member removal and bans {#88}

          status: open
          created: 2026-03-23 05:55:31 UTC
          updated: 2026-03-23 05:55:31 UTC

      Admins can remove members (who can rejoin if the channel is public) or ban them (preventing rejoin). Store bans in a channel_bans table with reason and timestamp.

  * ## Ticket: Task: Channel permissions {#16}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Per-channel permission overrides: who can post, pin messages, manage members, change settings.

  * ## Ticket: Task: Threads {#17}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Reply to a message to start a thread. Thread messages don't clutter the main channel. Thread notification preferences.

    * ## Ticket: Task: Thread creation and reply model {#89}

          status: open
          created: 2026-03-23 05:55:35 UTC
          updated: 2026-03-23 05:55:35 UTC

      Add a parent_message_id column to messages. Replies with a non-null parent form a thread. The parent message shows a reply count and preview of the latest reply in the main channel view.

    * ## Ticket: Task: Thread UI and navigation {#90}

          status: open
          created: 2026-03-23 05:55:35 UTC
          updated: 2026-03-23 05:55:35 UTC

      Clicking a threaded message opens a side panel showing the full thread. New replies appear in real-time via WebSocket. Provide a "back to channel" button and keyboard shortcut.

    * ## Ticket: Task: Thread notification preferences {#91}

          status: open
          created: 2026-03-23 05:55:35 UTC
          updated: 2026-03-23 05:55:35 UTC

      Users can choose per-thread: notify on all replies, only when mentioned, or never. Default to "all replies" for threads the user has participated in.

  * ## Ticket: Task: Pinned messages and bookmarks {#18}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Pin important messages to channel. Personal bookmarks across channels.

* ## Ticket: Epic: Media and file sharing {#19}

      status: open
      created: 2026-03-23 05:32:06 UTC
      updated: 2026-03-23 05:32:06 UTC

  Upload, store, and display images, videos, documents, and voice messages.

  * ## Ticket: Task: File upload pipeline {#20}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Chunked upload for large files, progress tracking, resume after interruption. Validate file types and size limits.

    * ## Ticket: Task: Chunked upload with resumability {#92}

          status: open
          created: 2026-03-23 05:55:42 UTC
          updated: 2026-03-23 05:55:42 UTC

      Split files into 5MB chunks client-side. Upload each chunk to a presigned S3 multipart URL. Track uploaded parts server-side so interrupted uploads can resume from the last successful chunk.

    * ## Ticket: Task: File validation and size limits {#93}

          status: open
          created: 2026-03-23 05:55:42 UTC
          updated: 2026-03-23 05:55:42 UTC

      Check MIME type against an allowlist (images, documents, audio, video). Enforce per-file size limit (100MB) and per-user storage quota. Reject disallowed types with a clear error message before upload begins.

    * ## Ticket: Task: Upload progress tracking {#94}

          status: open
          created: 2026-03-23 05:55:42 UTC
          updated: 2026-03-23 05:55:42 UTC

      Emit progress events from the upload handler (percentage, bytes transferred, estimated time remaining). Display a progress bar in the chat composer and allow the user to cancel mid-upload.

  * ## Ticket: Task: Image handling {#21}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Generate thumbnails on upload. Progressive loading with blur placeholder. Full-size viewer with zoom and pan.

    * ## Ticket: Task: Thumbnail generation {#95}

          status: open
          created: 2026-03-23 05:55:47 UTC
          updated: 2026-03-23 05:55:47 UTC

      On upload, generate thumbnails at multiple sizes (150px, 300px, 600px) using a background worker. Store thumbnails alongside the original in object storage. Strip EXIF data for privacy.

    * ## Ticket: Task: Progressive image loading {#96}

          status: open
          created: 2026-03-23 05:55:47 UTC
          updated: 2026-03-23 05:55:47 UTC

      Generate a tiny (20px) blurred placeholder at upload time. Render the blur placeholder immediately in chat, then swap to the full thumbnail once loaded. Use CSS transitions for a smooth reveal.

    * ## Ticket: Task: Full-size image viewer {#97}

          status: open
          created: 2026-03-23 05:55:47 UTC
          updated: 2026-03-23 05:55:47 UTC

      Lightbox overlay with zoom (mouse wheel / pinch), pan (drag), and navigation between images in the same conversation. Preload adjacent images. Close on Escape or clicking outside.

  * ## Ticket: Task: Video and audio messages {#22}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Record and send voice messages directly in chat. Video message recording with preview. Streaming playback.

    * ## Ticket: Task: Voice message recording {#98}

          status: open
          created: 2026-03-23 05:55:52 UTC
          updated: 2026-03-23 05:55:52 UTC

      In-chat microphone button to record audio using the MediaRecorder API. Show a waveform visualization during recording. Encode as Opus in WebM container for compact file size.

    * ## Ticket: Task: Video message recording and preview {#99}

          status: open
          created: 2026-03-23 05:55:52 UTC
          updated: 2026-03-23 05:55:52 UTC

      Capture video from the device camera with a configurable time limit (default 3min). Show a preview frame before sending. Transcode server-side to H.264/MP4 for broad playback compatibility.

    * ## Ticket: Task: Streaming playback {#100}

          status: open
          created: 2026-03-23 05:55:52 UTC
          updated: 2026-03-23 05:55:52 UTC

      Serve audio and video via HTTP range requests for streaming playback without full download. Display an inline player with play/pause, scrubber, and duration. Autoplay is off by default.

  * ## Ticket: Task: Document preview {#23}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    In-line preview for PDFs, spreadsheets, and presentations. Download button for unsupported formats.

* ## Ticket: Epic: Notifications {#24}

      status: open
      created: 2026-03-23 05:32:06 UTC
      updated: 2026-03-23 05:32:06 UTC

  Push, in-app, and email notifications with per-channel controls.

  * ## Ticket: Task: Push notification service {#25}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Integrate with APNs and FCM. Handle device token registration, payload formatting, and delivery tracking.

    * ## Ticket: Task: APNs and FCM integration {#101}

          status: open
          created: 2026-03-23 05:55:59 UTC
          updated: 2026-03-23 05:55:59 UTC

      Implement provider adapters for Apple Push Notification service and Firebase Cloud Messaging. Abstract behind a common interface so adding new providers (e.g., web push) requires only a new adapter.

    * ## Ticket: Task: Device token registration {#102}

          status: open
          created: 2026-03-23 05:55:59 UTC
          updated: 2026-03-23 05:55:59 UTC

      Endpoint for clients to register and unregister device tokens. Store tokens per user with platform type and last-active timestamp. Prune tokens that have been inactive for 90 days.

    * ## Ticket: Task: Push payload formatting and delivery {#103}

          status: open
          created: 2026-03-23 05:55:59 UTC
          updated: 2026-03-23 05:55:59 UTC

      Format notification payloads per platform requirements (APNs alert dict, FCM data message). Include message preview, sender name, and deep-link URL. Log delivery status and handle feedback for invalid tokens.

  * ## Ticket: Task: In-app notification center {#26}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Notification list with unread count badge. Group by channel. Mark as read individually or in bulk.

    * ## Ticket: Task: Notification data model and API {#104}

          status: open
          created: 2026-03-23 05:56:04 UTC
          updated: 2026-03-23 05:56:04 UTC

      Store notifications with type, actor, target, read/unread flag, and created_at. Provide paginated GET /notifications endpoint with filtering by read status and type.

    * ## Ticket: Task: Notification grouping and badge count {#105}

          status: open
          created: 2026-03-23 05:56:04 UTC
          updated: 2026-03-23 05:56:04 UTC

      Group notifications from the same channel into collapsed entries (e.g., "5 new messages in #general"). Maintain a real-time unread count pushed via WebSocket for the badge in the app header.

    * ## Ticket: Task: Mark as read actions {#106}

          status: open
          created: 2026-03-23 05:56:04 UTC
          updated: 2026-03-23 05:56:04 UTC

      Mark individual notifications as read on click. Provide "mark all as read" button that bulk-updates all unread notifications. Sync read state across devices via the WebSocket connection.

  * ## Ticket: Task: Notification preferences {#27}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Per-channel mute, per-conversation mute with duration, quiet hours, keyword alerts.

  * ## Ticket: Task: Email notification digests {#28}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Batch unread messages into periodic email digests. Configurable frequency: immediate, hourly, daily.

* ## Ticket: Epic: Search {#29}

      status: open
      created: 2026-03-23 05:32:06 UTC
      updated: 2026-03-23 05:32:06 UTC

  Full-text search across messages, files, and users.

  * ## Ticket: Task: Message search {#30}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Full-text search with Elasticsearch or similar. Filter by channel, sender, date range. Highlight matching terms.

    * ## Ticket: Task: Search index setup {#107}

          status: open
          created: 2026-03-23 05:56:08 UTC
          updated: 2026-03-23 05:56:08 UTC

      Configure an Elasticsearch index for messages with appropriate analyzers (standard + language-specific). Index message body, sender, channel, and timestamp. Keep the index in sync using a database change stream or outbox pattern.

    * ## Ticket: Task: Search query API {#108}

          status: open
          created: 2026-03-23 05:56:08 UTC
          updated: 2026-03-23 05:56:08 UTC

      GET /search/messages endpoint accepting a query string plus optional filters (channel_id, sender_id, date_from, date_to). Return paginated results with highlighted matching fragments.

    * ## Ticket: Task: Access control filtering {#109}

          status: open
          created: 2026-03-23 05:56:08 UTC
          updated: 2026-03-23 05:56:08 UTC

      Apply security filters at query time so users only see results from channels they belong to. For private channels and DMs, inject a terms filter on the user's channel membership list.

  * ## Ticket: Task: File and media search {#31}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Search files by name, type, and uploader. Filter by date and channel.

  * ## Ticket: Task: Search UI {#32}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Search bar with autocomplete suggestions. Results grouped by type. Jump to message in context.

    * ## Ticket: Task: Search bar with autocomplete {#110}

          status: open
          created: 2026-03-23 05:56:13 UTC
          updated: 2026-03-23 05:56:13 UTC

      Global search bar triggered by Ctrl+K / Cmd+K. Show autocomplete suggestions as the user types: recent searches, matching channel names, and user names. Debounce API calls by 300ms.

    * ## Ticket: Task: Results display and grouping {#111}

          status: open
          created: 2026-03-23 05:56:13 UTC
          updated: 2026-03-23 05:56:13 UTC

      Display results grouped by type (messages, files, people) in tabs or sections. Show message context (channel name, sender, timestamp) and file metadata (name, type, size). Highlight matched terms.

    * ## Ticket: Task: Jump to message in context {#112}

          status: open
          created: 2026-03-23 05:56:13 UTC
          updated: 2026-03-23 05:56:13 UTC

      Clicking a search result navigates to the source channel and scrolls to the matched message. Highlight the target message briefly with a background flash. Load surrounding messages for context.

* ## Ticket: Epic: Infrastructure and deployment {#33}

      status: open
      created: 2026-03-23 05:32:06 UTC
      updated: 2026-03-23 05:32:06 UTC

  CI/CD, monitoring, database, and production environment.

  * ## Ticket: Task: Database schema and migrations {#34}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Design schema for users, messages, channels, and media. Migration framework with rollback support.

    * ## Ticket: Task: Core schema design {#113}

          status: open
          created: 2026-03-23 05:56:20 UTC
          updated: 2026-03-23 05:56:20 UTC

      Design tables for users, conversations, messages, channels, channel_members, attachments, and notifications. Define indexes on foreign keys and common query patterns (messages by channel+time, unread counts).

    * ## Ticket: Task: Migration framework {#114}

          status: open
          created: 2026-03-23 05:56:20 UTC
          updated: 2026-03-23 05:56:20 UTC

      Set up a migration tool (e.g., Alembic, Flyway, or golang-migrate) with versioned migration files. Each migration must include both up and down operations to support rollback.

    * ## Ticket: Task: Seed data and test fixtures {#115}

          status: open
          created: 2026-03-23 05:56:20 UTC
          updated: 2026-03-23 05:56:20 UTC

      Create seed scripts that populate the database with realistic test data: sample users, channels, conversations, and messages. Use these for local development and integration test setup.

  * ## Ticket: Task: CI/CD pipeline {#35}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Automated test suite on PR. Staging deployment on merge. Production deployment with approval gate.

    * ## Ticket: Task: Test automation on PR {#116}

          status: open
          created: 2026-03-23 05:56:24 UTC
          updated: 2026-03-23 05:56:24 UTC

      Run unit tests, linting, and type checks on every pull request via GitHub Actions or similar. Block merge if any check fails. Cache dependencies between runs for faster feedback.

    * ## Ticket: Task: Staging deployment pipeline {#117}

          status: open
          created: 2026-03-23 05:56:24 UTC
          updated: 2026-03-23 05:56:24 UTC

      Auto-deploy the main branch to a staging environment on every merge. Run integration and smoke tests against staging after deployment. Notify the team channel on success or failure.

    * ## Ticket: Task: Production deployment with approval gate {#118}

          status: open
          created: 2026-03-23 05:56:24 UTC
          updated: 2026-03-23 05:56:24 UTC

      Production deploys require manual approval from at least one team lead. Use blue-green or canary deployment strategy. Automate rollback if health checks fail within 5 minutes of deployment.

  * ## Ticket: Task: Monitoring and alerting {#36}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Application metrics, error tracking, uptime monitoring. Alert on latency spikes, error rate increase, disk usage.

    * ## Ticket: Task: Application metrics collection {#119}

          status: open
          created: 2026-03-23 05:56:29 UTC
          updated: 2026-03-23 05:56:29 UTC

      Instrument the app with Prometheus metrics: request latency histograms, active WebSocket connections gauge, message throughput counter, and queue depths. Expose a /metrics endpoint for scraping.

    * ## Ticket: Task: Error tracking integration {#120}

          status: open
          created: 2026-03-23 05:56:29 UTC
          updated: 2026-03-23 05:56:29 UTC

      Integrate Sentry or equivalent for exception tracking. Capture unhandled errors with stack traces, request context, and user ID. Set up source maps for frontend error reports.

    * ## Ticket: Task: Alerting rules and on-call routing {#121}

          status: open
          created: 2026-03-23 05:56:29 UTC
          updated: 2026-03-23 05:56:29 UTC

      Define alert thresholds: p99 latency > 500ms, error rate > 1%, disk usage > 80%, WebSocket connection drops > 10% in 5min. Route alerts to PagerDuty or Opsgenie with escalation policies.

  * ## Ticket: Task: Rate limiting and abuse prevention {#37}

        status: open
        created: 2026-03-23 05:32:06 UTC
        updated: 2026-03-23 05:32:06 UTC

    Per-user rate limits on messages and API calls. Spam detection. Report and block users.

    * ## Ticket: Task: API rate limiting {#122}

          status: open
          created: 2026-03-23 05:56:33 UTC
          updated: 2026-03-23 05:56:33 UTC

      Implement token bucket rate limiting per user using Redis. Default limits: 60 requests/minute for general API, 30 messages/minute for sending. Return 429 with Retry-After header when exceeded.

    * ## Ticket: Task: Spam detection {#123}

          status: open
          created: 2026-03-23 05:56:33 UTC
          updated: 2026-03-23 05:56:33 UTC

      Flag accounts that send identical messages to multiple channels in rapid succession. Use a simple content fingerprint (hash of normalized text) and sliding window counter. Auto-mute flagged accounts pending review.

    * ## Ticket: Task: User reporting and blocking {#124}

          status: open
          created: 2026-03-23 05:56:33 UTC
          updated: 2026-03-23 05:56:33 UTC

      Allow users to report messages with a category (spam, harassment, other) and optional comment. Store reports for admin review. User-level blocking prevents the blocked user from sending DMs or appearing in search results.
