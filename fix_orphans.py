from circulation.models import BookCopy, BorrowingTransaction

def fix_orphaned_borrowed_copies():
    # Find all copies marked as 'borrowed'
    borrowed_copies = BookCopy.objects.filter(status='borrowed')
    fixed_count = 0
    
    for copy in borrowed_copies:
        # Check if there's an active borrowing transaction for this copy
        has_active_tx = BorrowingTransaction.objects.filter(
            copy=copy, status__in=['borrowed', 'overdue']
        ).exists()
        
        if not has_active_tx:
            # The copy is marked borrowed but no active transaction exists!
            # It's an orphan. Revert to available.
            copy.status = 'available'
            copy.save(update_fields=['status'])
            fixed_count += 1
            print(f"Fixed orphaned copy: {copy.accession_no} - {copy.book.title}")
            
    print(f"Total orphaned copies fixed: {fixed_count}")

if __name__ == "__main__":
    fix_orphaned_borrowed_copies()
