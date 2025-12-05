// Get all emails from Outlook
const items = $input.all();

console.log(`📧 Total emails retrieved: ${items.length}`);

// ============================================
// PROCESS ALL EMAILS (no filtering)
// ============================================
const BATCH_SIZE = 50; // Adjust as needed
const START_INDEX = 0;  // Change to 50, 100, 150... for next batches

// Take batch
const batch = items.slice(START_INDEX, START_INDEX + BATCH_SIZE);

console.log(`🔄 Processing emails: ${START_INDEX} to ${START_INDEX + BATCH_SIZE}`);
console.log(`✉️ Emails in this batch: ${batch.length}`);
console.log(`⏭️ Remaining: ${Math.max(0, items.length - (START_INDEX + BATCH_SIZE))} emails`);

// Prepare for API
const emails = batch.map(i => i.json);

// Extract user ID from first email
const userId = batch[0]?.json?.from?.emailAddress?.address || 
                batch[0]?.json?.sender?.emailAddress?.address || 
                "Lars.Kiebula@tu-steuer.de";

return [{
  json: {
    emails,
    user_id: userId
  }
}];