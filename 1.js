step 2 :

// Get all emails from Outlook
const items = $input.all();

console.log(`📧 Total emails retrieved: ${items.length}`);

// Filter to only include SENT emails (not received)
const sentEmails = items.filter(item => {
  const email = item.json;
  
  // Method 1: Check if email has 'sentDateTime' (only sent emails have this)
  const hasSentDate = email.sentDateTime !== undefined && email.sentDateTime !== null;
  
  // Method 2: Check the 'isDraft' flag (exclude drafts)
  const isNotDraft = email.isDraft === false || email.isDraft === undefined;
  
  // Method 3: Check if the email has recipients (sent emails have 'toRecipients')
  const hasRecipients = email.toRecipients && email.toRecipients.length > 0;
  
  // Method 4: Check conversationId or other metadata
  // Sent emails typically have different properties than received ones
  
  // Combine conditions: must be sent, not draft, and have recipients
  return hasSentDate && isNotDraft && hasRecipients;
});

console.log(`✅ Sent emails: ${sentEmails.length}`);
console.log(`❌ Filtered out: ${items.length - sentEmails.length}`);

// Return only sent emails
return sentEmails;







step 3 : 

// Get filtered sent emails
const items = $input.all();

// Configuration
const BATCH_SIZE = 50; // Process 50 emails at a time
const START_INDEX = 0; // Change this for each batch run

// Take a batch slice
const batch = items.slice(START_INDEX, START_INDEX + BATCH_SIZE);

console.log(`📦 Total sent emails: ${items.length}`);
console.log(`🔄 Processing batch: ${START_INDEX} to ${START_INDEX + BATCH_SIZE}`);
console.log(`✉️ Emails in this batch: ${batch.length}`);
console.log(`⏭️ Remaining: ${items.length - (START_INDEX + BATCH_SIZE)} emails`);

// Collect all message JSONs
const emails = batch.map(i => i.json);
const userId = batch[0]?.json?.from?.emailAddress?.address || "unknown_user";

return [{
  json: {
    emails,
    user_id: userId
  }
}];


