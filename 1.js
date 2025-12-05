// ============================================
// STEP 1: Get all emails from Outlook
// ============================================
const items = $input.all();

console.log(`📧 Total emails retrieved: ${items.length}`);

// ============================================
// STEP 2: Filter to SENT emails only
// ============================================
const sentEmails = items.filter(item => {
  const email = item.json;
  
  // Check if this is a sent email (not received)
  const hasSentDate = email.sentDateTime !== undefined && email.sentDateTime !== null;
  const isNotDraft = email.isDraft === false || email.isDraft === undefined;
  const hasRecipients = email.toRecipients && email.toRecipients.length > 0;
  
  // Must have all three conditions to be a sent email
  return hasSentDate && isNotDraft && hasRecipients;
});

console.log(`✅ Sent emails found: ${sentEmails.length}`);
console.log(`❌ Filtered out (received/drafts): ${items.length - sentEmails.length}`);

// ============================================
// STEP 3: Process in batches (optional)
// ============================================
const BATCH_SIZE = 50; // Adjust as needed: 25, 50, 100, etc.
const START_INDEX = 0;  // Change to 50, 100, 150... for subsequent runs

// Take batch
const batch = sentEmails.slice(START_INDEX, START_INDEX + BATCH_SIZE);

console.log(`🔄 Batch range: ${START_INDEX} to ${START_INDEX + BATCH_SIZE}`);
console.log(`📦 Processing: ${batch.length} emails`);
console.log(`⏭️ Remaining: ${Math.max(0, sentEmails.length - (START_INDEX + BATCH_SIZE))} emails`);

// ============================================
// STEP 4: Prepare for API
// ============================================
const emails = batch.map(i => i.json);

// Extract user ID from first email
const userId = batch[0]?.json?.from?.emailAddress?.address || "unknown_user";

return [{
  json: {
    emails,
    user_id: userId
  }
}];